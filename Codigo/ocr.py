"""Extracción local de texto y OCR de documentos de un expediente.

El módulo no modifica los archivos fuente.  El texto se conserva por página
para que las fases posteriores puedan usarlo como evidencia documental.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from xml.etree import ElementTree

from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .expediente import DocumentoExpediente, Expediente, read_expediente


class OCRExtractionError(RuntimeError):
    """Indica que un documento no pudo procesarse sin comprometer el expediente."""


@dataclass(frozen=True)
class TextoExtraido:
    """Texto recuperado de una página y su evidencia de origen."""

    documento: str
    pagina: int
    texto: str
    metodo: str
    confianza: float | None = None


@dataclass(frozen=True)
class ErrorOCR:
    """Error recuperable asociado a un documento o una página."""

    documento: str
    pagina: int | None
    detalle: str


@dataclass(frozen=True)
class ResultadoOCR:
    """Resultado completo de extraer el texto de un expediente."""

    id_expediente: str
    textos: tuple[TextoExtraido, ...]
    errores: tuple[ErrorOCR, ...]
    archivo_salida: str


def _ocr_logger(log_directory: Path) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.ocr.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "ocr.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _ocr_setting(configuration: ProjectConfiguration, name: str, default: object) -> object:
    settings = configuration.values.get("ocr", {})
    return settings.get(name, default) if isinstance(settings, dict) else default


def _source_path(configuration: ProjectConfiguration, document: DocumentoExpediente) -> Path:
    source = (configuration.project_root / document.ubicacion_original).resolve()
    try:
        source.relative_to(configuration.route("expedientes").resolve())
    except ValueError as error:
        raise OCRExtractionError("El documento está fuera de la ruta configurada de expedientes") from error
    return source


def _read_digital_pdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise OCRExtractionError("Falta la dependencia pypdf para leer PDF digitales") from error
    try:
        return [(page.extract_text() or "").strip() for page in PdfReader(str(path)).pages]
    except Exception as error:
        raise OCRExtractionError(f"No fue posible leer el PDF: {error}") from error


def _run_tesseract(image_path: Path, language: str, command: str, include_confidence: bool) -> tuple[str, float | None]:
    executable = shutil.which(command)
    if executable is None:
        raise OCRExtractionError(f"No se encontró el ejecutable OCR configurado: {command}")
    base_command = [executable, str(image_path), "stdout", "-l", language]
    try:
        text_result = subprocess.run(base_command, check=True, capture_output=True, text=True, encoding="utf-8")
        text = text_result.stdout.strip()
        if not include_confidence:
            return text, None
        tsv_result = subprocess.run(
            [*base_command, "tsv"], check=True, capture_output=True, text=True, encoding="utf-8"
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise OCRExtractionError(f"El OCR no pudo procesar la imagen: {error}") from error
    values: list[float] = []
    for line in tsv_result.stdout.splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) >= 11 and columns[10].strip():
            try:
                confidence = float(columns[10])
            except ValueError:
                continue
            if confidence >= 0:
                values.append(confidence)
    return text, round(mean(values), 2) if values else None


def _render_pdf_page(path: Path, page_number: int, command: str, resolution: int) -> Path:
    executable = shutil.which(command)
    if executable is None:
        raise OCRExtractionError(f"No se encontró el renderizador PDF configurado: {command}")
    temporary_directory = Path(tempfile.mkdtemp(prefix="gioj-ocr-"))
    output_prefix = temporary_directory / "pagina"
    try:
        subprocess.run(
            [executable, "-f", str(page_number), "-l", str(page_number), "-r", str(resolution), "-png", str(path), str(output_prefix)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        image = next(temporary_directory.glob("pagina-*.png"), None)
        if image is None:
            raise OCRExtractionError("El renderizador PDF no produjo una imagen de la página")
        return image
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def _extract_pdf(path: Path, document: DocumentoExpediente, configuration: ProjectConfiguration) -> list[TextoExtraido]:
    pages = _read_digital_pdf(path)
    language = str(_ocr_setting(configuration, "idioma", "spa"))
    tesseract = str(_ocr_setting(configuration, "comando_tesseract", "tesseract"))
    renderer = str(_ocr_setting(configuration, "comando_renderizador_pdf", "pdftoppm"))
    resolution = int(_ocr_setting(configuration, "resolucion_pdf", 300))
    include_confidence = bool(_ocr_setting(configuration, "registrar_confianza", True))
    results: list[TextoExtraido] = []
    for number, text in enumerate(pages, start=1):
        if text:
            if not bool(_ocr_setting(configuration, "permitir_pdf_digital", True)):
                raise OCRExtractionError("La extracción de PDF digitales está deshabilitada en la configuración")
            results.append(TextoExtraido(document.ubicacion_original, number, text, "PDF digital"))
            continue
        if not bool(_ocr_setting(configuration, "permitir_pdf_escaneado", True)):
            raise OCRExtractionError("El OCR de PDF escaneados está deshabilitado en la configuración")
        rendered_page = _render_pdf_page(path, number, renderer, resolution)
        try:
            ocr_text, confidence = _run_tesseract(rendered_page, language, tesseract, include_confidence)
        finally:
            shutil.rmtree(rendered_page.parent, ignore_errors=True)
        results.append(TextoExtraido(document.ubicacion_original, number, ocr_text, "OCR PDF escaneado", confidence))
    return results


def _extract_image(path: Path, document: DocumentoExpediente, configuration: ProjectConfiguration) -> list[TextoExtraido]:
    if not bool(_ocr_setting(configuration, "permitir_imagenes", True)):
        raise OCRExtractionError("El OCR de imágenes está deshabilitado en la configuración")
    text, confidence = _run_tesseract(
        path,
        str(_ocr_setting(configuration, "idioma", "spa")),
        str(_ocr_setting(configuration, "comando_tesseract", "tesseract")),
        bool(_ocr_setting(configuration, "registrar_confianza", True)),
    )
    return [TextoExtraido(document.ubicacion_original, 1, text, "OCR imagen", confidence)]


def _extract_docx(path: Path, document: DocumentoExpediente) -> list[TextoExtraido]:
    """Conserva el texto Word existente como una página lógica de evidencia."""
    namespace = {"word": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path) as archive:
            content = archive.read("word/document.xml")
        root = ElementTree.fromstring(content)
        paragraphs = ["".join(node.itertext()).strip() for node in root.findall(".//word:p", namespace)]
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise OCRExtractionError(f"No fue posible leer el documento Word: {error}") from error
    return [TextoExtraido(document.ubicacion_original, 1, "\n".join(item for item in paragraphs if item), "Documento Word")]


def _extract_document(path: Path, document: DocumentoExpediente, configuration: ProjectConfiguration) -> list[TextoExtraido]:
    if document.categoria == "PDF":
        return _extract_pdf(path, document, configuration)
    if document.categoria == "Imagen":
        return _extract_image(path, document, configuration)
    if path.suffix.casefold() == ".docx":
        return _extract_docx(path, document)
    raise OCRExtractionError(f"Formato no compatible para extracción: {path.suffix or 'sin extensión'}")


def _write_result(configuration: ProjectConfiguration, result: ResultadoOCR) -> Path:
    filename = str(_ocr_setting(configuration, "archivo_salida", "texto_extraido.json"))
    target_directory = configuration.route("salida") / result.id_expediente
    target_directory.mkdir(parents=True, exist_ok=True)
    target = (target_directory / filename).resolve()
    try:
        target.relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise OCRExtractionError("El archivo de salida OCR sale de la ruta configurada") from error
    payload = {"id_expediente": result.id_expediente, "textos": [asdict(item) for item in result.textos], "errores": [asdict(item) for item in result.errores]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def extract_expediente_text(project_root: Path, expediente_id: str) -> ResultadoOCR:
    """Extrae texto por página y registra errores sin interrumpir el expediente."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise OCRExtractionError(str(error)) from error
    expediente: Expediente = read_expediente(configuration.project_root, expediente_id)
    logger = _ocr_logger(configuration.route("logs"))
    texts: list[TextoExtraido] = []
    errors: list[ErrorOCR] = []
    if not bool(_ocr_setting(configuration, "habilitado", True)):
        detail = "El OCR está deshabilitado en la configuración"
        errors.extend(ErrorOCR(item.ubicacion_original, None, detail) for item in expediente.documentos)
        for error in errors:
            logger.error("OCR ERROR | %s | %s", error.documento, error.detalle)
        provisional = ResultadoOCR(expediente.id_expediente, (), tuple(errors), "")
        output = _write_result(configuration, provisional)
        return ResultadoOCR(expediente.id_expediente, (), tuple(errors), output.relative_to(configuration.project_root).as_posix())
    for document in expediente.documentos:
        try:
            extracted = _extract_document(_source_path(configuration, document), document, configuration)
        except OCRExtractionError as error:
            errors.append(ErrorOCR(document.ubicacion_original, None, str(error)))
            logger.error("OCR ERROR | %s | %s", document.ubicacion_original, error)
            continue
        texts.extend(extracted)
        for item in extracted:
            logger.info("TEXTO EXTRAIDO | %s | pagina=%s | metodo=%s", item.documento, item.pagina, item.metodo)
    provisional = ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), "")
    output = _write_result(configuration, provisional)
    relative_output = output.relative_to(configuration.project_root).as_posix()
    logger.info("OCR COMPLETADO | %s | %s texto(s) | %s error(es)", expediente.id_expediente, len(texts), len(errors))
    return ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), relative_output)
