"""Lectura segura de la estructura de expedientes de GIOJ."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigurationError, load_configuration


class ExpedienteError(ValueError):
    """Indica que una carpeta no puede utilizarse como expediente."""


@dataclass(frozen=True)
class DocumentoExpediente:
    """Referencia inmutable a un archivo del expediente, sin leer su contenido."""

    nombre: str
    ubicacion_original: str
    categoria: str


@dataclass(frozen=True)
class Expediente:
    """Inventario de documentos encontrados en un expediente."""

    id_expediente: str
    ubicacion_original: str
    documentos: tuple[DocumentoExpediente, ...]


_PDF_EXTENSIONS = {".pdf"}
_WORD_EXTENSIONS = {".doc", ".docx"}
_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _categorize(path: Path) -> str:
    """Identifica el formato por extensión, sin abrir el archivo."""
    extension = path.suffix.casefold()
    if extension in _PDF_EXTENSIONS:
        return "PDF"
    if extension in _WORD_EXTENSIONS:
        return "Documento Word"
    if extension in _IMAGE_EXTENSIONS:
        return "Imagen"
    return "Otro documento"


def _relative_to_project(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def _expediente_logger(log_directory: Path) -> logging.Logger:
    """Crea el registro de lectura sin registrar contenido documental."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.expediente.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "expediente.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _resolve_documents_directory(project_root: Path, expediente_id: str) -> tuple[Path, Path, Path]:
    """Resuelve ``Expedientes/{id}/01_Documentos`` y limita la lectura a Expedientes."""
    if not isinstance(expediente_id, str) or not expediente_id.strip():
        raise ExpedienteError("El identificador del expediente es obligatorio")
    candidate = Path(expediente_id.strip())
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {".", ".."}:
        raise ExpedienteError("El identificador del expediente no es válido")

    try:
        configuration = load_configuration(project_root)
        expedientes_root = configuration.route("expedientes")
    except ConfigurationError as error:
        raise ExpedienteError(str(error)) from error
    document_directory = (expedientes_root / candidate / "01_Documentos").resolve()
    try:
        document_directory.relative_to(expedientes_root.resolve())
    except ValueError as error:
        raise ExpedienteError("La carpeta seleccionada debe estar dentro de Expedientes") from error
    if not document_directory.is_dir():
        raise ExpedienteError("No se encontró la carpeta 01_Documentos del expediente")
    return configuration.project_root, expedientes_root.resolve(), document_directory


def find_expediente_id(project_root: Path, document_names: list[str]) -> str:
    """Identifica un expediente por los nombres adjuntos, sin abrir archivos."""
    if not isinstance(document_names, list) or not document_names or not all(isinstance(name, str) for name in document_names):
        raise ExpedienteError("La selección de documentos no es válida")
    try:
        configuration = load_configuration(project_root)
        root = configuration.project_root
        expedientes_root = configuration.route("expedientes").resolve()
    except ConfigurationError as error:
        raise ExpedienteError(str(error)) from error
    selected = Counter(Path(name).name for name in document_names if Path(name).name)
    if not selected:
        raise ExpedienteError("La selección de documentos no contiene nombres válidos")

    matches: list[str] = []
    for candidate in expedientes_root.iterdir():
        document_directory = candidate / "01_Documentos"
        if not candidate.is_dir() or not document_directory.is_dir():
            continue
        available = Counter(path.name for path in document_directory.rglob("*") if path.is_file())
        if not selected - available:
            matches.append(candidate.name)
    if len(matches) != 1:
        raise ExpedienteError(
            "No fue posible identificar una única carpeta de expediente con los documentos seleccionados"
        )
    return matches[0]


def read_expediente(project_root: Path, expediente_id: str) -> Expediente:
    """Construye el objeto Expediente sin procesar el contenido de sus documentos."""
    root, expedientes_root, document_directory = _resolve_documents_directory(project_root, expediente_id)
    logger = _expediente_logger(load_configuration(root).route("logs"))
    documents: list[DocumentoExpediente] = []

    for path in sorted(document_directory.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(expedientes_root)
        except ValueError:
            logger.warning("ARCHIVO OMITIDO | %s | fuera de Expedientes", _relative_to_project(path, root))
            continue
        document = DocumentoExpediente(
            nombre=path.name,
            ubicacion_original=_relative_to_project(path, root),
            categoria=_categorize(path),
        )
        documents.append(document)
        logger.info("ARCHIVO ENCONTRADO | %s | %s", document.categoria, document.ubicacion_original)

    expediente_path = document_directory.parent
    expediente = Expediente(
        id_expediente=expediente_path.name,
        ubicacion_original=_relative_to_project(expediente_path, root),
        documentos=tuple(documents),
    )
    logger.info("EXPEDIENTE CARGADO | %s | %s archivo(s)", expediente.id_expediente, len(expediente.documentos))
    return expediente
