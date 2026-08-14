"""Validaciones trazables interpretadas exclusivamente desde 04_Reglas_Negocio."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .clasificacion import (
    _normalizar,
    _read_shared_strings,
    _read_sheet,
    _worksheet_paths,
    load_document_types,
)
from .config import ConfigurationError, ProjectConfiguration, load_configuration


class ValidationError(ValueError):
    """No fue posible ejecutar las validaciones configuradas."""


@dataclass(frozen=True)
class ReglaNegocio:
    id_regla: str
    tipo_regla: str
    fuente_regla: str
    criterios: dict[str, str]


@dataclass(frozen=True)
class ComparacionValidacion:
    campo: str
    valor_esperado: str
    valor_encontrado: tuple[str, ...]
    documento_origen: tuple[str, ...]
    pagina_origen: tuple[int, ...]
    documento_destino: str
    estado: str
    observacion: str
    documento_validado: str = ""
    pagina_validada: int | None = None
    documento_comparado: str = ""
    pagina_comparada: int | None = None
    referencia_comparada: str = ""
    estado_interfaz: str = "No validado"


@dataclass(frozen=True)
class ResultadoValidacion:
    id_regla: str
    tipo_regla: str
    fuente_regla: str
    estado: str
    comparaciones: tuple[ComparacionValidacion, ...]
    observacion: str


@dataclass(frozen=True)
class ResumenValidacion:
    total_reglas_definidas: int
    total_validaciones: int
    cumple: int
    no_cumple: int
    no_existe_informacion: int
    no_aplica: int


@dataclass(frozen=True)
class ResultadoValidaciones:
    id_expediente: str
    validaciones: tuple[ResultadoValidacion, ...]
    archivo_salida: str
    resumen: ResumenValidacion


def _cell(row: dict[str, str], name: str) -> str:
    return row.get(name, "").strip()


def load_business_rules(configuration: ProjectConfiguration) -> tuple[ReglaNegocio, ...]:
    """Lee todas las filas identificadas de la hoja configurada de reglas."""
    try:
        sheet_name = str(configuration.values["hojas"]["reglas"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            rows = _read_sheet(workbook, _worksheet_paths(workbook)[sheet_name], _read_shared_strings(workbook))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise ValidationError(f"No fue posible leer 04_Reglas_Negocio: {error}") from error
    rules = tuple(
        ReglaNegocio(
            _cell(row, "ID_Regla"), _cell(row, "Tipo_Regla"), _cell(row, "Fuente_Regla"),
            {column: value.strip() for column, value in row.items()
             if column not in {"ID_Regla", "Tipo_Regla", "Fuente_Regla"} and value.strip()},
        )
        for row in rows if _cell(row, "ID_Regla")
    )
    if not rules:
        raise ValidationError("04_Reglas_Negocio no contiene reglas identificadas")
    duplicates = [item for item in dict.fromkeys(rule.id_regla for rule in rules) if sum(rule.id_regla == item for rule in rules) > 1]
    if duplicates:
        raise ValidationError("04_Reglas_Negocio contiene ID_Regla duplicados: " + ", ".join(duplicates))
    incomplete = [rule.id_regla for rule in rules if not rule.tipo_regla or not rule.criterios]
    if incomplete:
        raise ValidationError("04_Reglas_Negocio contiene definiciones incompletas: " + ", ".join(incomplete))
    return rules


def _path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    settings = configuration.values.get("validacion", {})
    filename = str(settings.get("archivo_salida", "validaciones_documentales.json")) if isinstance(settings, dict) else "validaciones_documentales.json"
    if Path(filename).name != filename:
        raise ValidationError("El archivo de validaciones debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _load_extraction(configuration: ProjectConfiguration, expediente_id: str) -> dict[str, Any]:
    settings = configuration.values.get("extraccion", {})
    filename = str(settings.get("archivo_salida", "extraccion_documental.json")) if isinstance(settings, dict) else "extraccion_documental.json"
    if Path(filename).name != filename:
        raise ValidationError("El archivo de extracción debe ser un nombre de archivo")
    source = configuration.route("salida") / expediente_id / filename
    if not source.is_file():
        raise ValidationError("No se encontró el resultado de extracción; ejecute primero las fases anteriores")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"No fue posible leer el resultado de extracción: {error}") from error
    if not isinstance(payload, dict) or payload.get("id_expediente") != expediente_id:
        raise ValidationError("El resultado de extracción no corresponde al expediente seleccionado")
    return payload


def _entry(value: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = evidence or {}
    page = evidence.get("pagina")
    return {"valor": value, "documento": str(evidence.get("documento", "")), "pagina": int(page) if isinstance(page, (int, float)) else None}


def _add_values(index: dict[str, list[dict[str, Any]]], field: dict[str, Any]) -> None:
    values = field.get("valores", [])
    if not isinstance(values, list):
        return
    evidences = field.get("evidencias", [])
    fallback = evidences[0] if isinstance(evidences, list) and evidences and isinstance(evidences[0], dict) else None
    entries = []
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("valor_encontrado"), str):
            entries.append(_entry(value["valor_encontrado"], value))
        elif isinstance(value, str):
            entries.append(_entry(value, fallback))
    for name in (field.get("campo"), field.get("id_campo")):
        if isinstance(name, str) and name.strip():
            index.setdefault(_normalizar(name), []).extend(entries)


def _field_values(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Indexa los campos extraídos, incluso cuando pertenecen a un objeto."""
    index: dict[str, list[dict[str, Any]]] = {}
    for field in payload.get("campos", []):
        if not isinstance(field, dict):
            continue
        _add_values(index, field)
        for item in field.get("objetos", []):
            if isinstance(item, dict):
                for child in item.get("campos", []):
                    if isinstance(child, dict):
                        _add_values(index, child)
    return index


def _as_decimal(value: str) -> Decimal | None:
    raw = value.strip().replace(" ", "")
    if not raw or not re.fullmatch(r"[+-]?[0-9.,Ee]+", raw):
        return None
    try:
        if "e" in raw.lower():
            return Decimal(raw.replace(",", ""))
        if raw.count(",") and raw.count("."):
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(",") > 1 or raw.count(".") > 1:
            raw = raw.replace(",", "").replace(".", "")
        elif raw.count(",") == 1 and len(raw.rsplit(",", 1)[1]) == 3:
            raw = raw.replace(",", "")
        elif raw.count(".") == 1 and len(raw.rsplit(".", 1)[1]) == 3:
            raw = raw.replace(".", "")
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _as_date(value: str) -> date | None:
    numeric = _as_decimal(value)
    if numeric is not None and numeric == numeric.to_integral_value() and 20000 <= numeric <= 60000:
        return date(1899, 12, 30) + timedelta(days=int(numeric))
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    return None


def _equal(expected: str, found: str) -> bool:
    expected_date, found_date = _as_date(expected), _as_date(found)
    if expected_date is not None and found_date is not None:
        return expected_date == found_date
    expected_number, found_number = _as_decimal(expected), _as_decimal(found)
    if expected_number is not None and found_number is not None:
        return expected_number == found_number
    return _normalizar(expected) == _normalizar(found)


def _comparison(column: str, expected: str, values: list[dict[str, Any]]) -> ComparacionValidacion:
    found = tuple(dict.fromkeys(str(item["valor"]) for item in values))
    documents = tuple(dict.fromkeys(item["documento"] for item in values if item["documento"]))
    pages = tuple(dict.fromkeys(item["pagina"] for item in values if item["pagina"] is not None))
    if not values:
        return ComparacionValidacion(column, expected, (), (), (), "04_Reglas_Negocio", "No existe información", "El campo fue definido por la arquitectura, pero no se extrajo información del expediente.")
    if any(_equal(expected, value) for value in found):
        return ComparacionValidacion(column, expected, found, documents, pages, "04_Reglas_Negocio", "Cumple", "El valor encontrado coincide con el criterio de la regla.")
    return ComparacionValidacion(column, expected, found, documents, pages, "04_Reglas_Negocio", "No cumple", "El valor encontrado no coincide con el criterio de la regla.")


def _criterion(rule: ReglaNegocio, name: str, default: str = "") -> str:
    normalized = _normalizar(name)
    return next((value for column, value in rule.criterios.items() if _normalizar(column) == normalized), default)


def _load_result(configuration: ProjectConfiguration, expediente_id: str, filename: str) -> dict[str, Any]:
    source = configuration.route("salida") / expediente_id / filename
    if not source.is_file():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("id_expediente") == expediente_id else {}


def _classification_index(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("documentos", []):
        if not isinstance(item, dict) or not isinstance(item.get("documento"), str):
            continue
        document_types = tuple(dict.fromkeys(
            str(value)
            for value in (
                item.get("tipo_documental"),
                item.get("tipo_documental_fisico"),
                item.get("codigo_tipo_documental"),
                item.get("rol_documental"),
            )
            if value
        ))
        result[item["documento"]] = "|".join(document_types)
    return result


def _document_type_key(value: str) -> tuple[str, ...]:
    connectors = {"de", "del", "el", "la", "para"}
    return tuple(token for token in _normalizar(value.replace("_", " ")).split() if token not in connectors)


def _documents_of_type(classifications: dict[str, str], document_type: str) -> tuple[str, ...]:
    wanted = _document_type_key(document_type)
    return tuple(
        document
        for document, current in classifications.items()
        if any(_document_type_key(part) == wanted for part in current.split("|"))
    )


def _matches_nearby(expression: str, text: str, window: int = 8) -> bool:
    """Tolera el orden del OCR sin confundir palabras alejadas en la página."""
    expected = set(_normalizar(expression).split())
    tokens = _normalizar(text).split()
    if not expected:
        return False
    size = max(len(expected), window)
    return any(expected.issubset(set(tokens[index:index + size])) for index in range(len(tokens)))


def _documents_matching_architecture_type(
    configuration: ProjectConfiguration,
    ocr: dict[str, Any],
    document_type: str,
) -> tuple[str, ...]:
    """Ubica por evidencia OCR un origen funcional definido en la arquitectura."""
    wanted = _normalizar(document_type)
    cache = ocr.setdefault("_documentos_funcionales", {})
    if isinstance(cache, dict) and isinstance(cache.get(wanted), tuple):
        return cache[wanted]
    definition = next(
        (
            item
            for item in load_document_types(configuration)
            if _normalizar(item.nombre) == wanted or _normalizar(item.codigo) == wanted
        ),
        None,
    )
    if definition is None:
        return ()
    documents: list[str] = []
    for item in ocr.get("textos", []):
        if not isinstance(item, dict):
            continue
        document = item.get("documento")
        text = item.get("texto")
        if (
            isinstance(document, str)
            and isinstance(text, str)
            and any(_matches_nearby(expression, text) for expression in definition.expresiones)
            and document not in documents
        ):
            documents.append(document)
    result = tuple(documents)
    if isinstance(cache, dict):
        cache[wanted] = result
    return result


def _ocr_pages(payload: dict[str, Any], documents: tuple[str, ...]) -> list[dict[str, Any]]:
    selected = set(documents)
    return [
        item for item in payload.get("textos", [])
        if isinstance(item, dict) and item.get("documento") in selected and isinstance(item.get("texto"), str)
    ]


def _all_field_entries(values: dict[str, list[dict[str, Any]]], field_id: str) -> list[dict[str, Any]]:
    return values.get(_normalizar(field_id), [])


def _matching_page(expected: str, pages: list[dict[str, Any]]) -> tuple[int | None, str]:
    normalized_expected = _normalizar(expected)
    if not normalized_expected:
        return None, ""
    expected_tokens = normalized_expected.split()
    compact_expected = re.sub(r"\W", "", expected, flags=re.UNICODE).casefold()
    best: tuple[float, int | None, str] = (0.0, None, "")
    for item in pages:
        text = str(item.get("texto", ""))
        normalized_text = _normalizar(text)
        if normalized_expected in normalized_text:
            return int(item.get("pagina", 0) or 0), text[:1200]
        compact_text = re.sub(r"\W", "", text, flags=re.UNICODE).casefold()
        if len(compact_expected) >= 5 and compact_expected.isdigit() and compact_expected in compact_text:
            return int(item.get("pagina", 0) or 0), text[:1200]
        text_tokens = set(normalized_text.split())
        score = sum(token in text_tokens for token in set(expected_tokens)) / max(1, len(set(expected_tokens)))
        if score > best[0]:
            best = (score, int(item.get("pagina", 0) or 0), text[:1200])
    return (best[1], best[2]) if best[0] >= 0.45 else (None, "")


def _interface_state(state: str) -> str:
    return "Validado" if state == "Cumple" else "No validado"


def _trace_comparison(
    field: str,
    expected: str,
    found: str,
    validated_document: str,
    validated_page: int | None,
    compared_document: str,
    compared_page: int | None,
    state: str,
    observation: str,
    reference: str = "",
) -> ComparacionValidacion:
    return ComparacionValidacion(
        field,
        expected,
        (found,) if found else (),
        (validated_document,) if validated_document else (),
        (validated_page,) if validated_page else (),
        compared_document,
        state,
        observation,
        validated_document,
        validated_page,
        compared_document,
        compared_page,
        reference,
        _interface_state(state),
    )


def _condition_applies(rule: ReglaNegocio, values: dict[str, list[dict[str, Any]]]) -> bool:
    condition = _criterion(rule, "Aplica_Si", "Siempre").strip()
    if not condition or _normalizar(condition) == "siempre":
        return True
    if "=" not in condition:
        return True
    field_id, expected = (part.strip() for part in condition.split("=", 1))
    if _normalizar(field_id) == "existe campo":
        return bool(_all_field_entries(values, expected))
    entries = _all_field_entries(values, field_id)
    return any(_equal(expected, str(entry.get("valor", ""))) for entry in entries)


def _not_applicable(rule: ReglaNegocio) -> ResultadoValidacion:
    return ResultadoValidacion(
        rule.id_regla,
        rule.tipo_regla,
        rule.fuente_regla,
        "No aplica",
        (),
        f"La condición {_criterion(rule, 'Aplica_Si')} no se cumple para este expediente.",
    )


def _validate_unique_document(rule: ReglaNegocio, classifications: dict[str, str]) -> ResultadoValidacion:
    document_type = _criterion(rule, "Documento_Validado", "Escritura_Firma")
    documents = _documents_of_type(classifications, document_type)
    state = "Cumple" if len(documents) == 1 else "No cumple" if documents else "No existe información"
    found = ", ".join(documents) or "No identificado"
    comparison = _trace_comparison(
        "Documento",
        f"Exactamente un {document_type}",
        found,
        found if len(documents) == 1 else "",
        None,
        "Clasificacion_Documental",
        None,
        state,
        f"Se identificaron {len(documents)} documentos del tipo {document_type}.",
    )
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), comparison.observacion)


def _validate_mandatory_field_legacy(
    rule: ReglaNegocio,
    values: dict[str, list[dict[str, Any]]],
    configuration: ProjectConfiguration,
    classifications: dict[str, str],
    ocr: dict[str, Any],
) -> ResultadoValidacion:
    field_id = _criterion(rule, "ID_Campo_Clausula") or _criterion(rule, "Fuente_Valor_Esperado")
    validated_type = _criterion(rule, "Documento_Validado", "Escritura_Firma")
    escritura_documents = _documents_of_type(classifications, validated_type)
    if not escritura_documents:
        escritura_documents = _documents_matching_architecture_type(configuration, ocr, validated_type)
    pages = _ocr_pages(ocr, escritura_documents)
    entries = _all_field_entries(values, field_id)
    source_types = tuple(part for part in _criterion(rule, "Documento_Comparado").split("|") if part)
    expected_entries = [
        entry for entry in entries
        if any(
            any(
                _document_type_key(part) == _document_type_key(source)
                for part in classifications.get(str(entry.get("documento", "")), "").split("|")
            )
            for source in source_types
        )
    ]
    if not expected_entries:
        expected_entries = [entry for entry in entries if entry.get("documento") not in escritura_documents]
    escritura_entries = [entry for entry in entries if entry.get("documento") in escritura_documents]
    expected_entry = expected_entries[0] if expected_entries else (entries[0] if entries else None)
    expected = str(expected_entry.get("valor", "")) if expected_entry else "Dato obligatorio"
    compared_document = str(expected_entry.get("documento", "")) if expected_entry else " | ".join(source_types)
    compared_page = expected_entry.get("pagina") if expected_entry else None
    found_entry = next((entry for entry in escritura_entries if _equal(expected, str(entry.get("valor", "")))), None)
    if found_entry:
        validated_page = found_entry.get("pagina")
        found = str(found_entry.get("valor", ""))
    else:
        validated_page, found = _matching_page(expected, pages) if expected_entry else (None, "")
    if expected_entry and validated_page:
        state = "Cumple"
        observation = "El dato obligatorio fue localizado en Escritura_Firma y conserva trazabilidad contra el documento fuente."
    elif expected_entry:
        state = "No cumple"
        observation = "El dato esperado del documento fuente no fue localizado en Escritura_Firma."
    else:
        state = "No existe información"
        observation = "No existe un valor fuente trazable para validar el dato obligatorio."
    comparison = _trace_comparison(
        field_id,
        expected,
        found,
        escritura_documents[0] if len(escritura_documents) == 1 else "Escritura_Firma",
        validated_page,
        compared_document,
        int(compared_page) if isinstance(compared_page, (int, float)) else None,
        state,
        observation,
    )
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), observation)


def _validate_mandatory_field(
    rule: ReglaNegocio,
    values: dict[str, list[dict[str, Any]]],
    configuration: ProjectConfiguration,
    classifications: dict[str, str],
    ocr: dict[str, Any],
) -> ResultadoValidacion:
    """Contrasta todos los valores fuente, no únicamente el primero."""
    field_id = _criterion(rule, "ID_Campo_Clausula") or _criterion(rule, "Fuente_Valor_Esperado")
    validated_type = _criterion(rule, "Documento_Validado", "Escritura_Firma")
    escritura_documents = _documents_of_type(classifications, validated_type)
    if not escritura_documents:
        escritura_documents = _documents_matching_architecture_type(configuration, ocr, validated_type)
    pages = _ocr_pages(ocr, escritura_documents)
    entries = _all_field_entries(values, field_id)
    source_types = tuple(part.strip() for part in _criterion(rule, "Documento_Comparado").split("|") if part.strip())

    def belongs_to_source(entry: dict[str, Any]) -> bool:
        classified = classifications.get(str(entry.get("documento", "")), "").split("|")
        return any(
            _document_type_key(part) == _document_type_key(source)
            for source in source_types
            for part in classified
        )

    expected_entries = [entry for entry in entries if belongs_to_source(entry)]
    if not expected_entries:
        expected_entries = [entry for entry in entries if entry.get("documento") not in escritura_documents]
    escritura_entries = [entry for entry in entries if entry.get("documento") in escritura_documents]
    unique_expected: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for entry in expected_entries:
        page = entry.get("pagina")
        key = (str(entry.get("valor", "")), str(entry.get("documento", "")), int(page) if isinstance(page, (int, float)) else None)
        unique_expected.setdefault(key, entry)

    comparisons: list[ComparacionValidacion] = []
    for expected_entry in unique_expected.values():
        expected = str(expected_entry.get("valor", ""))
        found_entry = next(
            (entry for entry in escritura_entries if _equal(expected, str(entry.get("valor", "")))),
            None,
        )
        if found_entry:
            validated_page = found_entry.get("pagina")
            found = str(found_entry.get("valor", ""))
        else:
            validated_page, found = _matching_page(expected, pages)
        state = "Cumple" if validated_page else "No cumple"
        observation = (
            "El dato obligatorio fue localizado en Escritura_Firma y conserva trazabilidad contra el documento fuente."
            if state == "Cumple"
            else "El dato esperado del documento fuente no fue localizado en Escritura_Firma."
        )
        source_page = expected_entry.get("pagina")
        comparisons.append(_trace_comparison(
            field_id,
            expected,
            found,
            escritura_documents[0] if len(escritura_documents) == 1 else "Escritura_Firma",
            int(validated_page) if isinstance(validated_page, (int, float)) else None,
            str(expected_entry.get("documento", "")),
            int(source_page) if isinstance(source_page, (int, float)) else None,
            state,
            observation,
        ))
    if not comparisons:
        observation = "No existe un valor fuente trazable para validar el dato obligatorio."
        comparisons.append(_trace_comparison(
            field_id, "Dato obligatorio", "",
            escritura_documents[0] if len(escritura_documents) == 1 else "Escritura_Firma",
            None, " | ".join(source_types), None,
            "No existe informaciÃ³n", observation,
        ))
    state = (
        "No existe informaciÃ³n"
        if all(item.estado == "No existe informaciÃ³n" for item in comparisons)
        else "No cumple" if any(item.estado != "Cumple" for item in comparisons)
        else "Cumple"
    )
    observation = (
        "Todos los valores obligatorios contrastados fueron localizados en Escritura_Firma."
        if state == "Cumple" else comparisons[0].observacion
    )
    return ResultadoValidacion(
        rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, tuple(comparisons), observation
    )


def _bookmark_text(document_path: Path, bookmark: str) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(document_path) as package:
            root = ElementTree.fromstring(package.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValidationError(f"No fue posible leer la minuta de conocimiento: {error}") from error
    for paragraph in root.findall(".//w:p", namespace):
        names = {item.attrib.get(f"{{{namespace['w']}}}name") for item in paragraph.findall("w:bookmarkStart", namespace)}
        if bookmark in names:
            return "".join(paragraph.itertext()).strip()
    return ""


def _fixed_minute_text(value: str) -> str:
    return re.sub(r"\{\{[^{}]+\}\}", " ", value)


def _clause_score(expected: str, text: str) -> float:
    expected_tokens = _normalizar(_fixed_minute_text(expected)).split()
    found_tokens = _normalizar(text).split()
    if not expected_tokens or not found_tokens:
        return 0.0
    shingles = {tuple(expected_tokens[index:index + 4]) for index in range(max(1, len(expected_tokens) - 3))}
    found = {tuple(found_tokens[index:index + 4]) for index in range(max(1, len(found_tokens) - 3))}
    return len(shingles & found) / max(1, len(shingles))


def _validate_clause(
    rule: ReglaNegocio,
    configuration: ProjectConfiguration,
    classifications: dict[str, str],
    ocr: dict[str, Any],
) -> ResultadoValidacion:
    bookmark_reference = _criterion(rule, "Fuente_Valor_Esperado")
    bookmark = bookmark_reference.split(":", 1)[1] if ":" in bookmark_reference else bookmark_reference
    minute_file = configuration.route("conocimiento") / str(configuration.values.get("conocimiento", {}).get("minuta_hipoteca", "Minutas/Minuta_hipoteca.docx"))
    expected = _bookmark_text(minute_file, bookmark)
    escritura_documents = _documents_of_type(classifications, "Escritura_Firma")
    pages = _ocr_pages(ocr, escritura_documents)
    equivalences = configuration.values.get("analisis", {}).get("equivalencias_juridicas", {})
    def comparable_text(text: str) -> str:
        if not isinstance(equivalences, dict):
            return text
        result = text
        for canonical, alternatives in equivalences.items():
            if not isinstance(alternatives, list):
                continue
            for alternative in alternatives:
                result = re.sub(re.escape(str(alternative)), str(canonical), result, flags=re.IGNORECASE)
        return result
    ordered_pages = sorted(pages, key=lambda item: int(item.get("pagina", 0) or 0))
    windows: list[tuple[str, dict[str, Any]]] = []
    for index, page in enumerate(ordered_pages):
        text = str(page.get("texto", ""))
        windows.append((text, page))
        if index + 1 < len(ordered_pages):
            windows.append((text + "\n" + str(ordered_pages[index + 1].get("texto", "")), page))
    best = max(
        ((_clause_score(expected, comparable_text(text)), page, text) for text, page in windows),
        default=(0.0, {}, ""),
        key=lambda pair: pair[0],
    )
    score, page, matched_text = best
    threshold = float(
        _criterion(rule, "Umbral_Comparacion")
        or configuration.values.get("analisis", {}).get("umbral_coincidencia_clausula", 0.8)
    )
    state = "Cumple" if expected and score >= threshold else "No cumple" if expected and pages else "No existe información"
    observation = (
        f"Coincidencia estructural de {score:.0%} con la sección {bookmark}."
        if expected and pages else "No existe texto suficiente para comparar la cláusula."
    )
    comparison = _trace_comparison(
        _criterion(rule, "ID_Campo_Clausula", rule.id_regla),
        expected[:1600],
        matched_text[:1600],
        escritura_documents[0] if len(escritura_documents) == 1 else "Escritura_Firma",
        int(page.get("pagina", 0) or 0) or None,
        "Minuta_hipoteca.docx",
        None,
        state,
        observation,
        bookmark,
    )
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), observation)


def _read_power_catalog(configuration: ProjectConfiguration) -> list[dict[str, str]]:
    relative = str(configuration.values.get("conocimiento", {}).get("poderes_ecopetrol", "Poderes/Poderes_ecopetrol_2026.xlsx"))
    source = configuration.route("conocimiento") / relative
    try:
        with zipfile.ZipFile(source) as workbook:
            paths = _worksheet_paths(workbook)
            first = next(iter(paths.values()))
            return _read_sheet(workbook, first, _read_shared_strings(workbook))
    except (OSError, StopIteration, ValueError, zipfile.BadZipFile) as error:
        raise ValidationError(f"No fue posible leer el catálogo de poderes: {error}") from error


def _validate_power(
    rule: ReglaNegocio,
    configuration: ProjectConfiguration,
    classifications: dict[str, str],
    ocr: dict[str, Any],
) -> ResultadoValidacion:
    catalog = _read_power_catalog(configuration)
    escritura_documents = _documents_of_type(classifications, "Escritura_Firma")
    pages = _ocr_pages(ocr, escritura_documents)
    full_text = "\n".join(str(item.get("texto", "")) for item in pages)
    reference = _criterion(rule, "Fuente_Valor_Esperado")
    candidates = [row for row in catalog if _normalizar(row.get("Estado", "")) == "vigente"]
    if reference.startswith("POD-R"):
        candidates = [row for row in candidates if row.get("ID_Regla") == reference]
    else:
        candidates = [row for row in candidates if row.get("Tipo_Regla") != "Poder_Matriz"]
    required_columns = ("Numero_Poder", "Fecha_Poder", "Notaria", "Ciudad_Notaria")

    def catalog_value_present(column: str, value: str) -> bool:
        if not value:
            return True
        if column == "Fecha_Poder":
            parsed = _as_date(value)
            if parsed is not None:
                variants = (
                    parsed.strftime("%d/%m/%Y"),
                    parsed.strftime("%d-%m-%Y"),
                    f"{parsed.day} de {('enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre')[parsed.month - 1]} de {parsed.year}",
                )
                return any(_normalizar(item) in _normalizar(full_text) for item in variants)
        return _normalizar(value) in _normalizar(full_text)

    matched = next(
        (row for row in candidates if all(catalog_value_present(column, row.get(column, "")) for column in required_columns)),
        None,
    )
    state = "Cumple" if matched else "No cumple" if pages else "No existe información"
    expected = "; ".join(
        f"{column}={matched.get(column, '')}" for column in ("Apoderado", "Numero_Documento", *required_columns)
    ) if matched else f"Registro vigente del catálogo ({reference})"
    page_number, found = _matching_page(str((matched or {}).get("Numero_Poder", "")), pages) if matched else (None, full_text[:1200])
    observation = "La cadena de poder coincide con un registro vigente del catálogo local." if matched else "No se encontró una coincidencia completa y vigente en el catálogo local de poderes."
    comparison = _trace_comparison(rule.id_regla, expected, found, escritura_documents[0] if len(escritura_documents) == 1 else "Escritura_Firma", page_number, "Poderes_ecopetrol_2026.xlsx", None, state, observation, (matched or {}).get("ID_Regla", reference))
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), observation)


def _validate_quality(rule: ReglaNegocio, classifications: dict[str, str], ocr: dict[str, Any]) -> ResultadoValidacion:
    documents = _documents_of_type(classifications, "Escritura_Firma")
    pages = _ocr_pages(ocr, documents)
    comparison_type = _criterion(rule, "Tipo_Comparacion")
    patterns = {
        "Sin_Marcadores": r"\{\{[^{}]+\}\}|_{4,}|\bxxx+\b",
        "Sin_Instrucciones": r"incluir unicamente|sin formato|validar informacion|representante de cavipetrol que firmara|hasta aca la minuta",
    }
    findings: list[tuple[dict[str, Any], str]] = []
    if comparison_type in patterns:
        expression = re.compile(patterns[comparison_type], re.IGNORECASE)
        for page in pages:
            match = expression.search(_normalizar(str(page.get("texto", ""))) if comparison_type == "Sin_Instrucciones" else str(page.get("texto", "")))
            if match:
                findings.append((page, match.group(0)))
    elif comparison_type == "Sin_Duplicados":
        anchors = ("acto seguido comparece", "registrada ante cavipetrol")
        normalized = _normalizar("\n".join(str(item.get("texto", "")) for item in pages))
        duplicate = next((anchor for anchor in anchors if normalized.count(anchor) > 1), "")
        if duplicate:
            findings.append((pages[0] if pages else {}, duplicate))
    elif comparison_type == "Orden_Secciones":
        normalized = _normalizar("\n".join(str(item.get("texto", "")) for item in pages))
        positions = [normalized.find(_normalizar(label)) for label in ("primera constitucion", "segunda objeto", "tercera cuantia", "cuarta tradicion")]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            findings.append((pages[0] if pages else {}, "orden de cláusulas"))
    state = "No cumple" if findings else "Cumple" if pages else "No existe información"
    page = findings[0][0] if findings else (pages[0] if pages else {})
    found = findings[0][1] if findings else "Sin hallazgos"
    observation = "Se encontró contenido que incumple el control de calidad." if findings else "No se encontraron hallazgos para este control de calidad."
    comparison = _trace_comparison(rule.id_regla, _criterion(rule, "Fuente_Valor_Esperado"), found, documents[0] if len(documents) == 1 else "Escritura_Firma", int(page.get("pagina", 0) or 0) or None, "Minuta_hipoteca.docx", None, state, observation)
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), observation)


def _validate_presence(
    rule: ReglaNegocio,
    values: dict[str, list[dict[str, Any]]],
    classifications: dict[str, str],
) -> ResultadoValidacion:
    field_id = _criterion(rule, "ID_Campo_Clausula") or _criterion(rule, "Fuente_Valor_Esperado")
    validated_type = _criterion(rule, "Documento_Validado", "Escritura_Firma")
    target_documents = _documents_of_type(classifications, validated_type)
    entries = [
        item for item in _all_field_entries(values, field_id)
        if not target_documents or item.get("documento") in target_documents
    ]
    entry = entries[0] if entries else None
    state = "Cumple" if entry else "No existe informaciÃ³n"
    observation = (
        "El campo obligatorio está presente en el documento validado."
        if entry else "No existe evidencia del campo obligatorio en el documento validado."
    )
    comparison = _trace_comparison(
        field_id,
        "Dato obligatorio presente",
        str(entry.get("valor", "")) if entry else "",
        str(entry.get("documento", "")) if entry else validated_type,
        int(entry.get("pagina")) if entry and isinstance(entry.get("pagina"), (int, float)) else None,
        "01_Campos_Extraccion",
        None,
        state,
        observation,
    )
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, (comparison,), observation)


def _validate_manual_responsibility(rule: ReglaNegocio) -> ResultadoValidacion:
    observation = (
        _criterion(rule, "Mensaje_Conformidad")
        or _criterion(rule, "Mensaje_Falla")
        or "Control reservado al analista; GIOJ no solicita ni genera este dato."
    )
    comparison = _trace_comparison(
        _criterion(rule, "Nombre_Regla", rule.id_regla),
        "Diligenciamiento manual por el analista",
        "No intervenido por GIOJ",
        "Analista",
        None,
        "04_Reglas_Negocio",
        None,
        "No aplica",
        observation,
    )
    return ResultadoValidacion(
        rule.id_regla, rule.tipo_regla, rule.fuente_regla, "No aplica", (comparison,), observation
    )


def _validate(
    rule: ReglaNegocio,
    values: dict[str, list[dict[str, Any]]],
    configuration: ProjectConfiguration | None = None,
    classifications: dict[str, str] | None = None,
    ocr: dict[str, Any] | None = None,
) -> ResultadoValidacion:
    comparison_type = _criterion(rule, "Tipo_Comparacion")
    if comparison_type and configuration is not None:
        classifications = classifications or {}
        ocr = ocr or {}
        if not _condition_applies(rule, values):
            return _not_applicable(rule)
        if comparison_type == "Responsabilidad_Manual":
            return _validate_manual_responsibility(rule)
        if comparison_type == "Documento_Unico":
            return _validate_unique_document(rule, classifications)
        if comparison_type in {"Campo_Obligatorio_Comparado", "Entidad_Representada"}:
            return _validate_mandatory_field(rule, values, configuration, classifications, ocr)
        if comparison_type == "Campo_Obligatorio_Presencia":
            return _validate_presence(rule, values, classifications)
        if comparison_type == "Clausula_Minuta":
            return _validate_clause(rule, configuration, classifications, ocr)
        if comparison_type == "Poder_Catalogo":
            return _validate_power(rule, configuration, classifications, ocr)
        if comparison_type in {"Sin_Marcadores", "Sin_Instrucciones", "Sin_Duplicados", "Orden_Secciones"}:
            return _validate_quality(rule, classifications, ocr)
    comparisons = tuple(_comparison(column, expected, values[_normalizar(column)]) for column, expected in rule.criterios.items() if _normalizar(column) in values)
    if not comparisons or any(item.estado == "No existe información" for item in comparisons):
        state, observation = "No existe información", "No hay campos extraídos que correspondan a los criterios de esta regla."
    elif any(item.estado == "No cumple" for item in comparisons):
        state, observation = "No cumple", "Al menos un criterio de la regla no coincide con el expediente."
    else:
        state, observation = "Cumple", "Todos los criterios disponibles de la regla coinciden."
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, comparisons, observation)


def _is_consolidation_rule(rule: ReglaNegocio) -> bool:
    return _criterion(rule, "Tipo_Comparacion") == "Consolidacion_Bloqueantes"


def _validate_consolidation(
    rule: ReglaNegocio,
    rules: tuple[ReglaNegocio, ...],
    completed: dict[str, ResultadoValidacion],
) -> ResultadoValidacion:
    """Aplica CON-001 a todas las reglas bloqueantes ya evaluadas."""
    blocking_rules = tuple(
        item
        for item in rules
        if item.id_regla != rule.id_regla
        and not _is_consolidation_rule(item)
        and _normalizar(_criterion(item, "Severidad")) == "bloqueante"
        and _normalizar(_criterion(item, "Estado", "Vigente")) == "vigente"
    )
    states = {item.id_regla: completed[item.id_regla].estado for item in blocking_rules}
    adverse = tuple(
        rule_id
        for rule_id, state in states.items()
        if state in {"No cumple", "No existe información"}
    )
    state = "No cumple" if adverse else "Cumple"
    found = (
        ", ".join(f"{rule_id}={states[rule_id]}" for rule_id in adverse)
        if adverse
        else f"{len(states)} regla(s) bloqueante(s) en Cumple o No aplica"
    )
    observation = (
        "Existe al menos una regla bloqueante adversa o sin evidencia suficiente; "
        "el resultado preliminar es No Conformidad."
        if adverse
        else "Todas las reglas bloqueantes aplicables cumplen o no aplican; "
        "el resultado preliminar es Conformidad."
    )
    comparison = _trace_comparison(
        "Resultado_Preliminar",
        "Todas las reglas bloqueantes aplicables en Cumple o No aplica",
        found,
        "Todas_Validaciones",
        None,
        "04_Reglas_Negocio",
        None,
        state,
        observation,
    )
    return ResultadoValidacion(
        rule.id_regla,
        rule.tipo_regla,
        rule.fuente_regla,
        state,
        (comparison,),
        observation,
    )


def _logger(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.validacion.{directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(directory / "validacion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def validate_expediente_data(project_root: Path, expediente_id: str) -> ResultadoValidaciones:
    """Aplica todas las reglas vigentes y persiste cada resultado con evidencia."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise ValidationError(str(error)) from error
    rules = load_business_rules(configuration)
    values = _field_values(_load_extraction(configuration, expediente_id))
    classifications = _classification_index(_load_result(configuration, expediente_id, "clasificacion_documental.json"))
    ocr_filename = str(configuration.values.get("ocr", {}).get("archivo_salida", "texto_extraido.json"))
    ocr = _load_result(configuration, expediente_id, ocr_filename)
    completed: dict[str, ResultadoValidacion] = {}
    for rule in rules:
        if not _is_consolidation_rule(rule):
            completed[rule.id_regla] = _validate(
                rule, values, configuration, classifications, ocr
            )
    for rule in rules:
        if _is_consolidation_rule(rule):
            completed[rule.id_regla] = _validate_consolidation(rule, rules, completed)
    validations = tuple(completed[rule.id_regla] for rule in rules)
    summary = ResumenValidacion(len(rules), len(validations), sum(item.estado == "Cumple" for item in validations), sum(item.estado == "No cumple" for item in validations), sum(item.estado == "No existe información" for item in validations), sum(item.estado == "No aplica" for item in validations))
    target = _path(configuration, expediente_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise ValidationError("El archivo de validaciones sale de la ruta de salida configurada") from error
    target.write_text(json.dumps({"id_expediente": expediente_id, "origen_reglas": "04_Reglas_Negocio", "validaciones": [asdict(item) for item in validations], "resumen": asdict(summary)}, ensure_ascii=False, indent=2), encoding="utf-8")
    logger = _logger(configuration.route("logs"))
    for item in validations:
        logger.info("VALIDACION | %s | %s | %s", item.id_regla, item.tipo_regla, item.estado)
    logger.info("VALIDACION COMPLETADA | %s | %s regla(s)", expediente_id, summary.total_validaciones)
    return ResultadoValidaciones(expediente_id, validations, target.relative_to(configuration.project_root).as_posix(), summary)
