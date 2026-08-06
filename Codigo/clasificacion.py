"""Clasificación documental basada exclusivamente en Arquitectura.xlsx."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .expediente import ExpedienteError, read_expediente


_MAIN_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REFERENCE = re.compile(r"([A-Z]+)")
_TOKEN = re.compile(r"[\w]+", flags=re.UNICODE)


class ClassificationError(ValueError):
    """Indica que no fue posible clasificar un expediente de forma segura."""


@dataclass(frozen=True)
class DocumentTypeDefinition:
    """Tipo documental y evidencia de texto obtenidos desde la arquitectura."""

    codigo: str
    nombre: str
    expresiones: tuple[str, ...]


@dataclass(frozen=True)
class EvidenciaClasificacion:
    """Coincidencia que explica por qué se asignó un tipo documental."""

    pagina: int
    valor_encontrado: str


@dataclass(frozen=True)
class DocumentoClasificado:
    """Resultado de clasificar uno de los documentos originales del expediente."""

    documento: str
    tipo_documental: str | None
    codigo_tipo_documental: str | None
    estado: str
    evidencias: tuple[EvidenciaClasificacion, ...]
    observacion: str


@dataclass(frozen=True)
class ResultadoClasificacion:
    """Resultado persistible de la clasificación de un expediente."""

    id_expediente: str
    documentos: tuple[DocumentoClasificado, ...]
    archivo_salida: str


def _normalizar(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    without_accents = "".join(character for character in decomposed if unicodedata.category(character) != "Mn")
    return " ".join(_TOKEN.findall(without_accents))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_normalizar(value).split())


def _column_index(reference: str) -> int:
    """Convierte la parte alfabética de una celda XLSX en su índice base cero."""
    match = _CELL_REFERENCE.match(reference)
    if not match:
        return 0
    index = 0
    for letter in match.group(1):
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    namespace = {"main": _MAIN_NAMESPACE}
    return ["".join(node.itertext()) for node in root.findall("main:si", namespace)]


def _worksheet_paths(workbook: zipfile.ZipFile) -> dict[str, str]:
    namespace = {"main": _MAIN_NAMESPACE, "rel": _RELATIONSHIP_NAMESPACE}
    package_namespace = {"rel": _PACKAGE_RELATIONSHIP_NAMESPACE}
    try:
        workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
        relationships_root = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ElementTree.ParseError) as error:
        raise ClassificationError(f"No fue posible leer Arquitectura.xlsx: {error}") from error
    relationships = {
        relation.attrib.get("Id"): relation.attrib.get("Target", "")
        for relation in relationships_root.findall("rel:Relationship", package_namespace)
    }
    paths: dict[str, str] = {}
    for sheet in workbook_root.findall("main:sheets/main:sheet", namespace):
        name = sheet.attrib.get("name")
        relationship_id = sheet.attrib.get(f"{{{_RELATIONSHIP_NAMESPACE}}}id")
        target = relationships.get(relationship_id)
        if not name or not target:
            continue
        paths[name] = "xl/" + target.lstrip("/") if not target.startswith("/") else target.lstrip("/")
    return paths


def _read_sheet(workbook: zipfile.ZipFile, path: str, shared_strings: list[str]) -> list[dict[str, str]]:
    namespace = {"main": _MAIN_NAMESPACE}
    try:
        root = ElementTree.fromstring(workbook.read(path))
    except (KeyError, ElementTree.ParseError) as error:
        raise ClassificationError(f"No fue posible leer una hoja de Arquitectura.xlsx: {error}") from error
    raw_rows: list[dict[int, str]] = []
    for row in root.findall("main:sheetData/main:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("main:c", namespace):
            cell_type = cell.attrib.get("t")
            reference = cell.attrib.get("r", "")
            value_node = cell.find("main:v", namespace)
            if cell_type == "inlineStr":
                text = "".join(cell.find("main:is", namespace).itertext()) if cell.find("main:is", namespace) is not None else ""
            elif value_node is None:
                text = ""
            elif cell_type == "s":
                try:
                    text = shared_strings[int(value_node.text or "")]
                except (IndexError, ValueError) as error:
                    raise ClassificationError("Arquitectura.xlsx contiene una referencia de texto inválida") from error
            else:
                text = value_node.text or ""
            values[_column_index(reference)] = text.strip()
        if values:
            raw_rows.append(values)
    if not raw_rows:
        return []
    header = raw_rows[0]
    return [
        {header[column]: value for column, value in row.items() if header.get(column)}
        for row in raw_rows[1:]
    ]


def _architecture_sheets(configuration: ProjectConfiguration) -> dict[str, list[dict[str, str]]]:
    architecture_path = configuration.route("arquitectura")
    try:
        with zipfile.ZipFile(architecture_path) as workbook:
            shared_strings = _read_shared_strings(workbook)
            paths = _worksheet_paths(workbook)
            requested = {
                "campos": configuration.values["hojas"]["campos"],
                "matriz": configuration.values["hojas"]["matriz"],
                "catalogos": configuration.values["hojas"]["catalogos"],
                "extraccion": configuration.values["hojas"]["extraccion"],
            }
            sheets = {
                key: _read_sheet(workbook, paths[name], shared_strings)
                for key, name in requested.items()
                if name in paths
            }
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ClassificationError(f"No fue posible abrir Arquitectura.xlsx: {error}") from error
    missing = {"campos", "matriz", "catalogos", "extraccion"} - sheets.keys()
    if missing:
        raise ClassificationError(f"Faltan hojas necesarias para clasificar: {', '.join(sorted(missing))}")
    return sheets


def _active(row: dict[str, str]) -> bool:
    return _normalizar(row.get("Activo", "")) not in {"0", "false", "no"}


def load_document_types(configuration: ProjectConfiguration) -> tuple[DocumentTypeDefinition, ...]:
    """Construye los tipos y evidencias de texto desde las hojas oficiales."""
    sheets = _architecture_sheets(configuration)
    catalog_rows = [row for row in sheets["catalogos"] if _active(row)]
    field_catalogs = {
        row.get("ID_Campo", ""): row.get("Catalogo_Asociado", "")
        for row in sheets["campos"]
        if row.get("ID_Campo")
    }
    catalogs: dict[str, list[str]] = defaultdict(list)
    document_catalog: list[tuple[str, str]] = []
    for row in catalog_rows:
        catalog, code, value = row.get("Catalogo", ""), row.get("Codigo", ""), row.get("Valor", "")
        if catalog and value:
            catalogs[catalog].append(value)
        if catalog == "Tipo_Documento_Expediente" and code and value:
            document_catalog.append((code, value))

    matrix_rows = sheets["matriz"]
    if not matrix_rows:
        raise ClassificationError("La matriz de origen documental no contiene definiciones")
    source_names = {
        column
        for row in matrix_rows
        for column, value in row.items()
        if column not in {"ID_Campo", "Entidad", "Campo", "Documento_Principal"}
        and _normalizar(value) in {"0", "1", "0 0", "1 0"}
    }
    if not source_names:
        raise ClassificationError("La matriz de origen documental no contiene columnas de documentos")

    source_expressions: dict[str, list[str]] = {source: [source.replace("_", " ")] for source in source_names}
    for row in sheets["extraccion"]:
        source, field_id = row.get("Documento_Origen", ""), row.get("ID_Campo", "")
        if source not in source_expressions:
            continue
        catalog = field_catalogs.get(field_id, "")
        source_expressions[source].extend(catalogs.get(catalog, []))

    definitions: list[DocumentTypeDefinition] = []
    unmatched_sources = set(source_names)
    for code, name in document_catalog:
        name_tokens = set(_tokens(name))
        related_sources = [
            source
            for source in source_names
            if set(_tokens(source.replace("_", " "))).issubset(name_tokens)
            or name_tokens.issubset(set(_tokens(source.replace("_", " "))))
        ]
        expressions = [name]
        for source in related_sources:
            expressions.extend(source_expressions[source])
            unmatched_sources.discard(source)
        definitions.append(DocumentTypeDefinition(code, name, tuple(dict.fromkeys(item for item in expressions if item))))
    for source in sorted(unmatched_sources):
        definitions.append(
            DocumentTypeDefinition(source, source.replace("_", " "), tuple(dict.fromkeys(source_expressions[source])))
        )
    if not definitions:
        raise ClassificationError("La arquitectura no define tipos documentales activos")
    return tuple(definitions)


def _matches(expression: str, text: str) -> bool:
    expression_tokens = _tokens(expression)
    if not expression_tokens:
        return False
    normalized_text = _normalizar(text)
    phrase = " ".join(expression_tokens)
    if phrase in normalized_text:
        return True
    text_tokens = set(normalized_text.split())
    return len(expression_tokens) > 1 and set(expression_tokens).issubset(text_tokens)


def _classify_document(
    document: str,
    pages: list[dict[str, Any]],
    definitions: tuple[DocumentTypeDefinition, ...],
) -> DocumentoClasificado:
    scores: dict[str, int] = defaultdict(int)
    evidences: dict[str, list[EvidenciaClasificacion]] = defaultdict(list)
    by_code = {definition.codigo: definition for definition in definitions}
    for page in pages:
        text = page.get("texto", "")
        if not isinstance(text, str) or not text.strip():
            continue
        for definition in definitions:
            matches = [expression for expression in definition.expresiones if _matches(expression, text)]
            if not matches:
                continue
            strongest = max(matches, key=lambda expression: len(_tokens(expression)))
            scores[definition.codigo] += len(_tokens(strongest))
            evidences[definition.codigo].append(EvidenciaClasificacion(int(page.get("pagina", 0) or 0), strongest))
    if not scores:
        observation = "No se encontró evidencia de un tipo documental definido en Arquitectura.xlsx."
        if not pages:
            observation = "No existe texto OCR disponible para este documento."
        return DocumentoClasificado(document, None, None, "No identificado", (), observation)
    highest_score = max(scores.values())
    winners = [code for code, score in scores.items() if score == highest_score]
    if len(winners) != 1:
        candidates = ", ".join(by_code[code].nombre for code in sorted(winners))
        return DocumentoClasificado(
            document,
            None,
            None,
            "No identificado",
            (),
            f"La evidencia coincide con más de un tipo documental: {candidates}.",
        )
    winner = by_code[winners[0]]
    unique_evidences = tuple(dict.fromkeys(evidences[winner.codigo]))
    return DocumentoClasificado(
        document,
        winner.nombre,
        winner.codigo,
        "Identificado",
        unique_evidences,
        "Tipo documental identificado mediante evidencia OCR y definiciones de Arquitectura.xlsx.",
    )


def _classification_logger(log_directory: Path) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.clasificacion.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "clasificacion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _ocr_file(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    filename = str(configuration.values.get("ocr", {}).get("archivo_salida", "texto_extraido.json"))
    if Path(filename).name != filename:
        raise ClassificationError("El archivo de salida OCR debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _load_ocr_texts(configuration: ProjectConfiguration, expediente_id: str) -> list[dict[str, Any]]:
    source = _ocr_file(configuration, expediente_id)
    if not source.is_file():
        raise ClassificationError("No se encontró el texto OCR del expediente; ejecute primero la extracción documental")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClassificationError(f"No fue posible leer el resultado OCR: {error}") from error
    if payload.get("id_expediente") != expediente_id or not isinstance(payload.get("textos"), list):
        raise ClassificationError("El resultado OCR no corresponde al expediente o tiene un formato inválido")
    return [item for item in payload["textos"] if isinstance(item, dict)]


def _write_result(configuration: ProjectConfiguration, result: ResultadoClasificacion) -> Path:
    target = configuration.route("salida") / result.id_expediente / "clasificacion_documental.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise ClassificationError("El archivo de clasificación sale de la ruta de salida configurada") from error
    payload = {
        "id_expediente": result.id_expediente,
        "documentos": [asdict(document) for document in result.documentos],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def classify_expediente_documents(project_root: Path, expediente_id: str) -> ResultadoClasificacion:
    """Clasifica todos los documentos originales a partir del resultado OCR y la arquitectura."""
    try:
        configuration = load_configuration(project_root)
        expediente = read_expediente(configuration.project_root, expediente_id)
    except (ConfigurationError, ExpedienteError) as error:
        raise ClassificationError(str(error)) from error
    definitions = load_document_types(configuration)
    texts_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for text in _load_ocr_texts(configuration, expediente.id_expediente):
        document = text.get("documento")
        if isinstance(document, str):
            texts_by_document[document].append(text)
    documents = tuple(
        _classify_document(document.ubicacion_original, texts_by_document[document.ubicacion_original], definitions)
        for document in expediente.documentos
    )
    provisional = ResultadoClasificacion(expediente.id_expediente, documents, "")
    output = _write_result(configuration, provisional)
    logger = _classification_logger(configuration.route("logs"))
    for document in documents:
        logger.info(
            "CLASIFICACION DOCUMENTAL | %s | %s | %s",
            document.documento,
            document.estado,
            document.codigo_tipo_documental or "sin tipo",
        )
    logger.info("CLASIFICACION COMPLETADA | %s | %s documento(s)", expediente.id_expediente, len(documents))
    return ResultadoClasificacion(expediente.id_expediente, documents, output.relative_to(configuration.project_root).as_posix())
