"""Extracción local de texto y OCR de documentos de un expediente.

El módulo no modifica los archivos fuente.  El texto se conserva por página
para que las fases posteriores puedan usarlo como evidencia documental.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from statistics import mean
from typing import Callable
from xml.etree import ElementTree

from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .expediente import ArchivoSeleccionado, DocumentoExpediente, Expediente, read_expediente


class OCRExtractionError(RuntimeError):
    """Indica que un documento no pudo procesarse sin comprometer el expediente."""


DocumentProgressCallback = Callable[[str, int | None, str], None]
ProgressCallback = Callable[[str, int | None, int, int, str], None]


@dataclass(frozen=True)
class TextoExtraido:
    """Texto recuperado de una página y su evidencia de origen."""

    documento: str
    pagina: int
    texto: str
    metodo: str
    confianza: float | None = None
    texto_segunda_lectura: str | None = None
    confianza_segunda_lectura: float | None = None
    coincidencia_lecturas: float | None = None
    estado_verificacion: str = "No requerida"


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


def _digital_text_requires_ocr(text: str, configuration: ProjectConfiguration) -> bool:
    """Decide si el texto incrustado de un PDF es demasiado degradado.

    Algunos PDF contienen una capa de texto, pero sus glifos se recuperan con
    sustituciones que impiden identificar etiquetas y valores. La verificación
    visual se limita a esos casos y conserva el OCR como evidencia de página.
    """
    if not bool(_ocr_setting(configuration, "verificar_calidad_pdf_digital", True)):
        return False
    visible = [character for character in text if not character.isspace()]
    if not visible:
        return True
    allowed_punctuation = set(".,;:-()/º°%$#")
    irregular = sum(
        not (character.isalnum() or character in allowed_punctuation)
        for character in visible
    )
    quality = max(0.0, 1.0 - (5.0 * irregular / len(visible)))
    threshold = float(_ocr_setting(configuration, "umbral_calidad_pdf_digital", 0.82))
    return quality < threshold


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


def _run_tesseract(
    image_path: Path,
    language: str,
    command: str,
    include_confidence: bool,
    psm: int | None = None,
) -> tuple[str, float | None]:
    executable = shutil.which(command)
    if executable is None:
        raise OCRExtractionError(f"No se encontró el ejecutable OCR configurado: {command}")
    base_command = [executable, str(image_path), "stdout", "-l", language]
    if psm is not None:
        base_command.extend(["--psm", str(psm)])
    try:
        if not include_confidence:
            result = subprocess.run(base_command, check=True, capture_output=True, text=True, encoding="utf-8")
            return result.stdout.strip(), None
        result = subprocess.run([*base_command, "tsv"], check=True, capture_output=True, text=True, encoding="utf-8")
    except OSError as error:
        raise OCRExtractionError(f"El OCR no pudo iniciarse: {error}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip() or f"código de salida {error.returncode}"
        raise OCRExtractionError(f"El OCR no pudo procesar la imagen: {detail}") from error
    values: list[float] = []
    words_by_line: dict[tuple[str, str, str, str], list[str]] = {}
    for line in result.stdout.splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) >= 12 and columns[11].strip():
            line_key = (columns[1], columns[2], columns[3], columns[4])
            words_by_line.setdefault(line_key, []).append(columns[11].strip())
            try:
                confidence = float(columns[10])
            except ValueError:
                continue
            if confidence >= 0:
                values.append(confidence)
    text = "\n".join(" ".join(words) for words in words_by_line.values()).strip()
    return text, round(mean(values), 2) if values else None


def _run_tesseract_bytes(
    image_content: bytes,
    language: str,
    command: str,
    include_confidence: bool,
    psm: int | None = None,
) -> tuple[str, float | None]:
    """Ejecuta OCR desde entrada estándar para no crear una copia del archivo seleccionado."""
    executable = shutil.which(command)
    if executable is None:
        raise OCRExtractionError(f"No se encontró el ejecutable OCR configurado: {command}")
    base_command = [executable, "stdin", "stdout", "-l", language]
    if psm is not None:
        base_command.extend(["--psm", str(psm)])
    try:
        result = subprocess.run(
            [*base_command, "tsv"] if include_confidence else base_command,
            input=image_content,
            check=True,
            capture_output=True,
        )
    except OSError as error:
        raise OCRExtractionError(f"El OCR no pudo iniciarse: {error}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", errors="replace").strip() or f"código de salida {error.returncode}"
        raise OCRExtractionError(f"El OCR no pudo procesar la imagen: {detail}") from error
    output = result.stdout.decode("utf-8", errors="replace")
    if not include_confidence:
        return output.strip(), None
    values: list[float] = []
    words_by_line: dict[tuple[str, str, str, str], list[str]] = {}
    for line in output.splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) >= 12 and columns[11].strip():
            line_key = (columns[1], columns[2], columns[3], columns[4])
            words_by_line.setdefault(line_key, []).append(columns[11].strip())
            try:
                confidence = float(columns[10])
            except ValueError:
                continue
            if confidence >= 0:
                values.append(confidence)
    text = "\n".join(" ".join(words) for words in words_by_line.values()).strip()
    return text, round(mean(values), 2) if values else None


def _text_similarity(first: str, second: str) -> float:
    left = " ".join(first.casefold().split())
    right = " ".join(second.casefold().split())
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(SequenceMatcher(None, left, right).ratio(), 4)


def _verified_ocr_file(
    image_path: Path,
    configuration: ProjectConfiguration,
) -> tuple[str, float | None, str | None, float | None, float | None, str]:
    language = str(_ocr_setting(configuration, "idioma", "spa"))
    command = str(_ocr_setting(configuration, "comando_tesseract", "tesseract"))
    include_confidence = bool(_ocr_setting(configuration, "registrar_confianza", True))
    primary_psm = int(_ocr_setting(configuration, "psm_primario", 3))
    primary_text, primary_confidence = _run_tesseract(
        image_path, language, command, include_confidence, primary_psm
    )
    enabled = bool(_ocr_setting(configuration, "doble_lectura_condicional", False))
    threshold = float(_ocr_setting(configuration, "umbral_confianza_segunda_lectura", 85))
    if not enabled or (primary_text and primary_confidence is not None and primary_confidence >= threshold):
        return primary_text, primary_confidence, None, None, None, "No requerida"
    secondary_psm = int(_ocr_setting(configuration, "psm_secundario", 6))
    secondary_text, secondary_confidence = _run_tesseract(
        image_path, language, command, include_confidence, secondary_psm
    )
    similarity = _text_similarity(primary_text, secondary_text)
    minimum_similarity = float(_ocr_setting(configuration, "umbral_coincidencia_segunda_lectura", 0.72))
    state = "Coincidente" if similarity >= minimum_similarity else "Divergente; revisión semántica requerida"
    if (secondary_confidence or -1) > (primary_confidence or -1):
        return secondary_text, secondary_confidence, primary_text, primary_confidence, similarity, state
    return primary_text, primary_confidence, secondary_text, secondary_confidence, similarity, state


def _verified_ocr_bytes(
    image_content: bytes,
    configuration: ProjectConfiguration,
) -> tuple[str, float | None, str | None, float | None, float | None, str]:
    language = str(_ocr_setting(configuration, "idioma", "spa"))
    command = str(_ocr_setting(configuration, "comando_tesseract", "tesseract"))
    include_confidence = bool(_ocr_setting(configuration, "registrar_confianza", True))
    primary_psm = int(_ocr_setting(configuration, "psm_primario", 3))
    primary_text, primary_confidence = _run_tesseract_bytes(
        image_content, language, command, include_confidence, primary_psm
    )
    enabled = bool(_ocr_setting(configuration, "doble_lectura_condicional", False))
    threshold = float(_ocr_setting(configuration, "umbral_confianza_segunda_lectura", 85))
    if not enabled or (primary_text and primary_confidence is not None and primary_confidence >= threshold):
        return primary_text, primary_confidence, None, None, None, "No requerida"
    secondary_psm = int(_ocr_setting(configuration, "psm_secundario", 6))
    secondary_text, secondary_confidence = _run_tesseract_bytes(
        image_content, language, command, include_confidence, secondary_psm
    )
    similarity = _text_similarity(primary_text, secondary_text)
    minimum_similarity = float(_ocr_setting(configuration, "umbral_coincidencia_segunda_lectura", 0.72))
    state = "Coincidente" if similarity >= minimum_similarity else "Divergente; revisión semántica requerida"
    if (secondary_confidence or -1) > (primary_confidence or -1):
        return secondary_text, secondary_confidence, primary_text, primary_confidence, similarity, state
    return primary_text, primary_confidence, secondary_text, secondary_confidence, similarity, state


def _render_pdfium_page_bytes(content: bytes, page_number: int, resolution: int) -> bytes:
    """Renderiza con PDFium cuando la dependencia está disponible."""
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(content)
        page = document[page_number - 1]
        bitmap = page.render(scale=resolution / 72)
        image = bitmap.to_pil()
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except Exception as error:
        raise OCRExtractionError(f"No fue posible renderizar la página PDF en memoria: {error}") from error


def _configured_executable(command: str) -> str | None:
    """Resuelve el comando configurado y prefiere un ejecutable nativo en PATH."""
    resolved = shutil.which(command)
    if resolved and Path(resolved).suffix.casefold() == ".exe":
        return resolved
    if not Path(command).suffix:
        for directory in os.get_exec_path():
            candidate = Path(directory) / f"{command}.exe"
            if candidate.is_file():
                return str(candidate)
    return resolved


def _render_pdf_page_bytes(
    content: bytes,
    page_number: int,
    resolution: int,
    command: str = "pdftoppm",
) -> bytes:
    """Renderiza desde memoria con PDFium o el renderizador configurado."""
    try:
        return _render_pdfium_page_bytes(content, page_number, resolution)
    except ImportError:
        executable = _configured_executable(command)
        if executable is None:
            raise OCRExtractionError(
                f"No se encontró el renderizador PDF configurado: {command}"
            )
        try:
            result = subprocess.run(
                [
                    executable,
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-singlefile",
                    "-r",
                    str(resolution),
                    "-png",
                    "-",
                ],
                input=content,
                check=True,
                capture_output=True,
            )
        except OSError as error:
            raise OCRExtractionError(f"El renderizador PDF no pudo iniciarse: {error}") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or b"").decode("utf-8", errors="replace").strip()
            raise OCRExtractionError(
                f"No fue posible renderizar la página PDF en memoria: {detail or error.returncode}"
            ) from error
        if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise OCRExtractionError("El renderizador PDF no produjo una imagen PNG válida")
        return result.stdout


def _render_pdf_page(path: Path, page_number: int, command: str, resolution: int) -> Path:
    executable = _configured_executable(command)
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


def _extract_pdf(
    path: Path,
    document: DocumentoExpediente,
    configuration: ProjectConfiguration,
    progress: DocumentProgressCallback | None = None,
) -> list[TextoExtraido]:
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
            if progress:
                progress(document.ubicacion_original, number, "Extrayendo texto del PDF digital")
            if not _digital_text_requires_ocr(text, configuration):
                results.append(TextoExtraido(document.ubicacion_original, number, text, "PDF digital"))
                continue
            if progress:
                progress(document.ubicacion_original, number, "Verificando texto digital mediante OCR")
            rendered_page = _render_pdf_page(path, number, renderer, resolution)
            try:
                verified = _verified_ocr_file(rendered_page, configuration)
            finally:
                shutil.rmtree(rendered_page.parent, ignore_errors=True)
            results.append(TextoExtraido(
                document.ubicacion_original, number, verified[0], "OCR de verificación de PDF digital",
                verified[1], text, None, verified[4], verified[5],
            ))
            continue
        if not bool(_ocr_setting(configuration, "permitir_pdf_escaneado", True)):
            raise OCRExtractionError("El OCR de PDF escaneados está deshabilitado en la configuración")
        if progress:
            progress(document.ubicacion_original, number, "Aplicando OCR al PDF escaneado")
        rendered_page = _render_pdf_page(path, number, renderer, resolution)
        try:
            verified = _verified_ocr_file(rendered_page, configuration)
        finally:
            shutil.rmtree(rendered_page.parent, ignore_errors=True)
        results.append(TextoExtraido(
            document.ubicacion_original,
            number,
            verified[0],
            "OCR PDF escaneado",
            verified[1],
            verified[2],
            verified[3],
            verified[4],
            verified[5],
        ))
    return results


def _extract_image(
    path: Path,
    document: DocumentoExpediente,
    configuration: ProjectConfiguration,
    progress: DocumentProgressCallback | None = None,
) -> list[TextoExtraido]:
    if not bool(_ocr_setting(configuration, "permitir_imagenes", True)):
        raise OCRExtractionError("El OCR de imágenes está deshabilitado en la configuración")
    if progress:
        progress(document.ubicacion_original, 1, "Aplicando OCR a la imagen")
    verified = _verified_ocr_file(path, configuration)
    return [TextoExtraido(
        document.ubicacion_original, 1, verified[0], "OCR imagen", verified[1],
        verified[2], verified[3], verified[4], verified[5]
    )]


def _extract_docx(
    path: Path, document: DocumentoExpediente, progress: DocumentProgressCallback | None = None
) -> list[TextoExtraido]:
    """Conserva el texto Word existente como una página lógica de evidencia."""
    if progress:
        progress(document.ubicacion_original, 1, "Extrayendo texto del documento Word")
    namespace = {"word": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path) as archive:
            content = archive.read("word/document.xml")
        root = ElementTree.fromstring(content)
        paragraphs = ["".join(node.itertext()).strip() for node in root.findall(".//word:p", namespace)]
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise OCRExtractionError(f"No fue posible leer el documento Word: {error}") from error
    return [TextoExtraido(document.ubicacion_original, 1, "\n".join(item for item in paragraphs if item), "Documento Word")]


def _extract_memory_document(
    selected: ArchivoSeleccionado,
    configuration: ProjectConfiguration,
    progress: DocumentProgressCallback | None = None,
) -> list[TextoExtraido]:
    """Extrae un archivo seleccionado sin escribir su contenido en disco."""
    document = selected.documento
    content = selected.contenido
    include_confidence = bool(_ocr_setting(configuration, "registrar_confianza", True))
    language = str(_ocr_setting(configuration, "idioma", "spa"))
    tesseract = str(_ocr_setting(configuration, "comando_tesseract", "tesseract"))
    renderer = str(_ocr_setting(configuration, "comando_renderizador_pdf", "pdftoppm"))
    if document.categoria == "PDF":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise OCRExtractionError("Falta la dependencia pypdf para leer PDF digitales") from error
        try:
            pages = [(page.extract_text() or "").strip() for page in PdfReader(BytesIO(content)).pages]
        except Exception as error:
            raise OCRExtractionError(f"No fue posible leer el PDF: {error}") from error
        results: list[TextoExtraido] = []
        for number, text in enumerate(pages, start=1):
            if text:
                if not bool(_ocr_setting(configuration, "permitir_pdf_digital", True)):
                    raise OCRExtractionError("La extracción de PDF digitales está deshabilitada en la configuración")
                if progress:
                    progress(document.ubicacion_original, number, "Extrayendo texto del PDF digital")
                if not _digital_text_requires_ocr(text, configuration):
                    results.append(TextoExtraido(document.ubicacion_original, number, text, "PDF digital"))
                    continue
                if progress:
                    progress(document.ubicacion_original, number, "Verificando texto digital mediante OCR")
                image_content = _render_pdf_page_bytes(
                    content,
                    number,
                    int(_ocr_setting(configuration, "resolucion_pdf", 300)),
                    renderer,
                )
                verified = _verified_ocr_bytes(image_content, configuration)
                results.append(TextoExtraido(
                    document.ubicacion_original, number, verified[0], "OCR de verificación de PDF digital",
                    verified[1], text, None, verified[4], verified[5],
                ))
                continue
            if progress:
                progress(document.ubicacion_original, number, "Aplicando OCR al PDF escaneado")
            if not bool(_ocr_setting(configuration, "permitir_pdf_escaneado", True)):
                raise OCRExtractionError("El OCR de PDF escaneados está deshabilitado en la configuración")
            image_content = _render_pdf_page_bytes(
                content,
                number,
                int(_ocr_setting(configuration, "resolucion_pdf", 300)),
                renderer,
            )
            verified = _verified_ocr_bytes(image_content, configuration)
            results.append(TextoExtraido(
                document.ubicacion_original,
                number,
                verified[0],
                "OCR PDF escaneado",
                verified[1],
                verified[2],
                verified[3],
                verified[4],
                verified[5],
            ))
        return results
    if document.categoria == "Imagen":
        if not bool(_ocr_setting(configuration, "permitir_imagenes", True)):
            raise OCRExtractionError("El OCR de imágenes está deshabilitado en la configuración")
        if progress:
            progress(document.ubicacion_original, 1, "Aplicando OCR a la imagen")
        verified = _verified_ocr_bytes(content, configuration)
        return [TextoExtraido(
            document.ubicacion_original, 1, verified[0], "OCR imagen", verified[1],
            verified[2], verified[3], verified[4], verified[5]
        )]
    if Path(document.nombre).suffix.casefold() == ".docx":
        if progress:
            progress(document.ubicacion_original, 1, "Extrayendo texto del documento Word")
        namespace = {"word": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                xml_content = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml_content)
            paragraphs = ["".join(node.itertext()).strip() for node in root.findall(".//word:p", namespace)]
        except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise OCRExtractionError(f"No fue posible leer el documento Word: {error}") from error
        text = "\n".join(item for item in paragraphs if item)
        return [TextoExtraido(document.ubicacion_original, 1, text, "Documento Word")]
    raise OCRExtractionError(f"Formato no compatible para extracción: {Path(document.nombre).suffix or 'sin extensión'}")


def _extract_document(
    path: Path,
    document: DocumentoExpediente,
    configuration: ProjectConfiguration,
    progress: DocumentProgressCallback | None = None,
) -> list[TextoExtraido]:
    if document.categoria == "PDF":
        return _extract_pdf(path, document, configuration, progress)
    if document.categoria == "Imagen":
        return _extract_image(path, document, configuration, progress)
    if path.suffix.casefold() == ".docx":
        return _extract_docx(path, document, progress)
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


def _document_work_units(path: Path, document: DocumentoExpediente) -> int:
    """Calcula unidades de avance sin extraer ni modificar contenido."""
    if document.categoria != "PDF":
        return 1
    try:
        from pypdf import PdfReader

        return max(1, len(PdfReader(str(path)).pages))
    except Exception:
        return 1


def extract_expediente_text(
    project_root: Path, expediente_id: str, progress: ProgressCallback | None = None
) -> ResultadoOCR:
    """Extrae texto por página y registra errores sin interrumpir el expediente."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise OCRExtractionError(str(error)) from error
    expediente: Expediente = read_expediente(configuration.project_root, expediente_id)
    logger = _ocr_logger(configuration.route("logs"))
    texts: list[TextoExtraido] = []
    errors: list[ErrorOCR] = []
    initial = ResultadoOCR(expediente.id_expediente, (), (), "")
    _write_result(configuration, initial)
    if not bool(_ocr_setting(configuration, "habilitado", True)):
        detail = "El OCR está deshabilitado en la configuración"
        errors.extend(ErrorOCR(item.ubicacion_original, None, detail) for item in expediente.documentos)
        for error in errors:
            logger.error("OCR ERROR | %s | %s", error.documento, error.detalle)
        provisional = ResultadoOCR(expediente.id_expediente, (), tuple(errors), "")
        output = _write_result(configuration, provisional)
        return ResultadoOCR(expediente.id_expediente, (), tuple(errors), output.relative_to(configuration.project_root).as_posix())
    documents_with_units = [
        (
            document,
            _document_work_units(_source_path(configuration, document), document) if progress else 1,
        )
        for document in expediente.documentos
    ]
    total_units = sum(units for _, units in documents_with_units)
    completed_units = 0
    if progress:
        progress("", None, 0, total_units, "Preparando el expediente")
    for document, document_units in documents_with_units:
        if progress:
            progress(
                document.ubicacion_original,
                None,
                completed_units,
                total_units,
                "Iniciando documento",
            )

        def report_document_progress(documento: str, pagina: int | None, etapa: str) -> None:
            page_offset = max(0, min(document_units, (pagina or 1) - 1))
            if progress:
                progress(
                    documento,
                    pagina,
                    completed_units + page_offset,
                    total_units,
                    etapa,
                )

        try:
            extracted = _extract_document(
                _source_path(configuration, document), document, configuration, report_document_progress
            )
        except OCRExtractionError as error:
            errors.append(ErrorOCR(document.ubicacion_original, None, str(error)))
            logger.error("OCR ERROR | %s | %s", document.ubicacion_original, error)
            _write_result(
                configuration, ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), "")
            )
            completed_units += document_units
            if progress:
                progress(
                    document.ubicacion_original,
                    None,
                    completed_units,
                    total_units,
                    "Documento finalizado con error",
                )
            continue
        texts.extend(extracted)
        for item in extracted:
            logger.info("TEXTO EXTRAIDO | %s | pagina=%s | metodo=%s", item.documento, item.pagina, item.metodo)
        _write_result(configuration, ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), ""))
        completed_units += document_units
        if progress:
            progress(
                document.ubicacion_original,
                None,
                completed_units,
                total_units,
                "Documento completado",
            )
    provisional = ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), "")
    output = _write_result(configuration, provisional)
    relative_output = output.relative_to(configuration.project_root).as_posix()
    logger.info("OCR COMPLETADO | %s | %s texto(s) | %s error(es)", expediente.id_expediente, len(texts), len(errors))
    return ResultadoOCR(expediente.id_expediente, tuple(texts), tuple(errors), relative_output)


def extract_selected_files_text(
    project_root: Path,
    selection_id: str,
    files: tuple[ArchivoSeleccionado, ...],
    progress: ProgressCallback | None = None,
) -> ResultadoOCR:
    """Extrae archivos recibidos por la interfaz, conservándolos únicamente en memoria."""
    if not files:
        raise OCRExtractionError("Seleccione al menos un archivo para analizar")
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise OCRExtractionError(str(error)) from error
    logger = _ocr_logger(configuration.route("logs"))
    texts: list[TextoExtraido] = []
    errors: list[ErrorOCR] = []
    _write_result(configuration, ResultadoOCR(selection_id, (), (), ""))
    if not bool(_ocr_setting(configuration, "habilitado", True)):
        detail = "El OCR está deshabilitado en la configuración"
        errors.extend(ErrorOCR(item.documento.nombre, None, detail) for item in files)
        provisional = ResultadoOCR(selection_id, (), tuple(errors), "")
        output = _write_result(configuration, provisional)
        return ResultadoOCR(selection_id, (), tuple(errors), output.relative_to(configuration.project_root).as_posix())
    units: list[int] = []
    for selected in files:
        if selected.documento.categoria == "PDF":
            try:
                from pypdf import PdfReader

                units.append(max(1, len(PdfReader(BytesIO(selected.contenido)).pages)))
            except Exception:
                units.append(1)
        else:
            units.append(1)
    total_units = sum(units)
    completed_units = 0
    if progress:
        progress("", None, 0, total_units, "Preparando archivos seleccionados")
    for selected, document_units in zip(files, units):
        document = selected.documento
        if progress:
            progress(document.nombre, None, completed_units, total_units, "Iniciando documento")

        def report_document_progress(documento: str, pagina: int | None, etapa: str) -> None:
            page_offset = max(0, min(document_units, (pagina or 1) - 1))
            if progress:
                progress(documento, pagina, completed_units + page_offset, total_units, etapa)

        try:
            extracted = _extract_memory_document(selected, configuration, report_document_progress)
        except OCRExtractionError as error:
            errors.append(ErrorOCR(document.nombre, None, str(error)))
            logger.error("OCR ERROR | %s | %s", document.nombre, error)
            completed_units += document_units
            _write_result(configuration, ResultadoOCR(selection_id, tuple(texts), tuple(errors), ""))
            continue
        texts.extend(extracted)
        for item in extracted:
            logger.info("TEXTO EXTRAIDO | %s | pagina=%s | metodo=%s", item.documento, item.pagina, item.metodo)
        completed_units += document_units
        _write_result(configuration, ResultadoOCR(selection_id, tuple(texts), tuple(errors), ""))
        if progress:
            progress(document.nombre, None, completed_units, total_units, "Documento completado")
    provisional = ResultadoOCR(selection_id, tuple(texts), tuple(errors), "")
    output = _write_result(configuration, provisional)
    relative_output = output.relative_to(configuration.project_root).as_posix()
    logger.info("OCR COMPLETADO | %s | %s texto(s) | %s error(es)", selection_id, len(texts), len(errors))
    return ResultadoOCR(selection_id, tuple(texts), tuple(errors), relative_output)
