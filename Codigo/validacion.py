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

from .clasificacion import _normalizar, _read_shared_strings, _read_sheet, _worksheet_paths
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


def _rules(configuration: ProjectConfiguration) -> tuple[ReglaNegocio, ...]:
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


def _validate(rule: ReglaNegocio, values: dict[str, list[dict[str, Any]]]) -> ResultadoValidacion:
    comparisons = tuple(_comparison(column, expected, values[_normalizar(column)]) for column, expected in rule.criterios.items() if _normalizar(column) in values)
    if not comparisons or any(item.estado == "No existe información" for item in comparisons):
        state, observation = "No existe información", "No hay campos extraídos que correspondan a los criterios de esta regla."
    elif any(item.estado == "No cumple" for item in comparisons):
        state, observation = "No cumple", "Al menos un criterio de la regla no coincide con el expediente."
    else:
        state, observation = "Cumple", "Todos los criterios disponibles de la regla coinciden."
    return ResultadoValidacion(rule.id_regla, rule.tipo_regla, rule.fuente_regla, state, comparisons, observation)


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
    rules = _rules(configuration)
    values = _field_values(_load_extraction(configuration, expediente_id))
    validations = tuple(_validate(rule, values) for rule in rules)
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
