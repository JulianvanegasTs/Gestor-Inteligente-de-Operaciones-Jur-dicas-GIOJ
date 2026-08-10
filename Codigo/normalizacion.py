"""Normalización trazable según la hoja ``10_Formateadores``."""

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


class NormalizationError(ValueError):
    """La extracción o la arquitectura no permiten normalizar."""


@dataclass(frozen=True)
class Formateador:
    id_formateador: str
    nombre: str
    tipo_entrada: str
    campos_entrada: tuple[str, ...]
    formato_salida: str
    regla_formateo: str
    observaciones: str


@dataclass(frozen=True)
class Normalizacion:
    id_formateador: str
    nombre_formateador: str
    campos_entrada: tuple[str, ...]
    valor_original: str | tuple[str, ...] | dict[str, str]
    valor_normalizado: str
    evidencias: tuple[dict[str, Any], ...]
    objeto_indice: int | None = None


@dataclass(frozen=True)
class ResumenNormalizacion:
    total_formateadores_definidos: int
    total_formateadores_aplicados: int
    total_normalizaciones: int
    formateadores_sin_datos: tuple[str, ...]


@dataclass(frozen=True)
class ResultadoNormalizacion:
    id_expediente: str
    normalizaciones: tuple[Normalizacion, ...]
    advertencias_configuracion: tuple[str, ...]
    archivo_salida: str
    resumen: ResumenNormalizacion


_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_MONTHS_BY_NAME = {_normalizar(name): index for index, name in enumerate(_MONTHS, 1)}
_ORDINALS = {1: "Primera (1a)", 2: "Segunda (2a)", 3: "Tercera (3a)", 4: "Cuarta (4a)", 5: "Quinta (5a)", 6: "Sexta (6a)", 7: "Séptima (7a)", 8: "Octava (8a)", 9: "Novena (9a)"}
_UNITS = ("", "Uno", "Dos", "Tres", "Cuatro", "Cinco", "Seis", "Siete", "Ocho", "Nueve")
_TEENS = {10: "Diez", 11: "Once", 12: "Doce", 13: "Trece", 14: "Catorce", 15: "Quince", 16: "Dieciséis", 17: "Diecisiete", 18: "Dieciocho", 19: "Diecinueve"}
_TENS = {20: "Veinte", 30: "Treinta", 40: "Cuarenta", 50: "Cincuenta", 60: "Sesenta", 70: "Setenta", 80: "Ochenta", 90: "Noventa"}


def _cell(row: dict[str, str], name: str) -> str:
    return row.get(name, "").strip()


def _formatters(configuration: ProjectConfiguration) -> tuple[Formateador, ...]:
    try:
        name = str(configuration.values["hojas"]["formateadores"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            rows = _read_sheet(workbook, _worksheet_paths(workbook)[name], _read_shared_strings(workbook))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise NormalizationError(f"No fue posible leer 10_Formateadores: {error}") from error
    result = tuple(
        Formateador(
            _cell(row, "ID_Formateador"), _cell(row, "Nombre_Formateador"),
            _cell(row, "Tipo_Entrada"), tuple(value.strip() for value in _cell(row, "Campos_Entrada").split(",") if value.strip()),
            _cell(row, "Formato_Salida"), _cell(row, "Regla_Formateo"), _cell(row, "Observaciones"),
        ) for row in rows if _cell(row, "ID_Formateador")
    )
    if not result:
        raise NormalizationError("10_Formateadores no contiene formateadores definidos")
    duplicate_ids = [item for item in dict.fromkeys(value.id_formateador for value in result) if sum(value.id_formateador == item for value in result) > 1]
    if duplicate_ids:
        raise NormalizationError("10_Formateadores contiene ID_Formateador duplicados: " + ", ".join(duplicate_ids))
    invalid = [value.id_formateador for value in result if not value.nombre or not value.campos_entrada or not value.regla_formateo]
    if invalid:
        raise NormalizationError("10_Formateadores tiene definiciones incompletas: " + ", ".join(invalid))
    return result


def _path(configuration: ProjectConfiguration, section: str, default: str, expediente_id: str) -> Path:
    settings = configuration.values.get(section, {})
    filename = str(settings.get("archivo_salida", default)) if isinstance(settings, dict) else default
    if Path(filename).name != filename:
        raise NormalizationError(f"El archivo de {section} debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _load(path: Path, expediente_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise NormalizationError("No se encontró el resultado de extracción; ejecute primero la fase anterior")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NormalizationError(f"No fue posible leer el resultado de extracción: {error}") from error
    if not isinstance(payload, dict) or payload.get("id_expediente") != expediente_id:
        raise NormalizationError("El resultado de extracción no corresponde al expediente seleccionado")
    return payload


def _evidence(value: dict[str, Any]) -> dict[str, Any]:
    names = ("documento", "pagina", "metodo", "confianza", "evidencia_textual", "id_extraccion", "documento_origen", "prioridad", "heredado", "calidad")
    return {name: value[name] for name in names if name in value}


def _values(field: dict[str, Any]) -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (value["valor_encontrado"], _evidence(value)) for value in field.get("valores", [])
        if isinstance(value, dict) and isinstance(value.get("valor_encontrado"), str)
    )


def _matches(formatter: Formateador, field: dict[str, Any]) -> bool:
    return any(
        isinstance(source, str) and _normalizar(source) == _normalizar(target)
        for target in formatter.campos_entrada
        for source in (field.get("id_campo"), field.get("campo"), field.get("tipo_dato"))
    )


def _long_date(value: str) -> str:
    raw = " ".join(value.split())
    try:
        if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", raw):
            parsed = date(1899, 12, 30) + timedelta(days=int(Decimal(raw.replace(",", "."))))
        else:
            parsed = None
            for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
                try:
                    parsed = datetime.strptime(raw, pattern).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError
    except ValueError:
        match = re.fullmatch(r"(\d{1,2}) de ([A-Za-zÁÉÍÓÚáéíóúÑñ]+) de (\d{4})", raw)
        if not match or _normalizar(match.group(2)) not in _MONTHS_BY_NAME:
            raise NormalizationError(f"Fecha no reconocida por el formateador: {value}")
        parsed = date(int(match.group(3)), _MONTHS_BY_NAME[_normalizar(match.group(2))], int(match.group(1)))
    return f"{parsed.day} de {_MONTHS[parsed.month - 1]} de {parsed.year}"


def _currency(value: str) -> str:
    raw = re.sub(r"[^0-9,\.\-+Ee]", "", value)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif raw.count(",") > 1:
        raw = raw.replace(",", "")
    try:
        amount = Decimal(raw).quantize(Decimal("1"))
    except InvalidOperation as error:
        raise NormalizationError(f"Moneda no reconocida por el formateador: {value}") from error
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,}".replace(",", ".")


def _notary(value: str) -> str:
    match = re.search(r"\d+", value)
    if not match:
        raise NormalizationError(f"Número de notaría no reconocido por el formateador: {value}")
    number = int(match.group())
    if number in _ORDINALS:
        return _ORDINALS[number]
    if number in _TEENS:
        word = _TEENS[number]
    elif 21 <= number <= 29:
        word = "Veinti" + _UNITS[number - 20].lower()
    elif number in _TENS:
        word = _TENS[number]
    elif 30 < number < 100:
        tens, units = divmod(number, 10)
        word = f"{_TENS[tens * 10]} y {_UNITS[units].lower()}"
    else:
        raise NormalizationError(f"Número de notaría fuera del formato definido: {value}")
    return f"{word} ({number})"


def _formatter_applies(formatter: Formateador, value: str) -> bool:
    """Respeta las particiones explícitas de los formateadores de notaría."""
    if _normalizar(formatter.nombre) != "notaria_texto":
        return True
    match = re.search(r"\d+", value)
    if not match:
        return True
    number = int(match.group())
    observation = _normalizar(formatter.observaciones)
    if "1 a la 9" in observation:
        return 1 <= number <= 9
    if "desde la 10" in observation:
        return number >= 10
    return True


def _scalar(formatter: Formateador, value: str) -> str:
    name = _normalizar(formatter.nombre)
    if name == "largo_espanol":
        return _long_date(value)
    if name == "formato_moneda":
        return _currency(value)
    if name == "nombre_completo":
        return " ".join(value.split())
    if name == "notaria_texto":
        return _notary(value)
    if name == "estado_civil":
        if _normalizar(value) != "casado":
            raise NormalizationError(f"Estado civil sin formato definido: {value}")
        return "Casado(a)"
    raise NormalizationError(f"{formatter.id_formateador} requiere resultados de otra fase")


def _object_value(formatter: Formateador, components: dict[str, str]) -> str:
    if formatter.nombre == "Documento_Identidad":
        if "PER-003" in components and "PER-004" in components:
            return f"{components['PER-003'].strip()} No. {components['PER-004'].strip()}"
    if formatter.nombre == "Referencia_Credito":
        if "CRE-002" in components and "CRE-003" in components:
            return f"{components['CRE-003'].strip()} - {components['CRE-002'].strip()}"
    raise NormalizationError(f"{formatter.id_formateador} no tiene todos los campos definidos por la arquitectura")


def _objects(formatter: Formateador, fields: list[dict[str, Any]]) -> tuple[Normalizacion, ...]:
    result: list[Normalizacion] = []
    requested = set(formatter.campos_entrada)
    for entity in fields:
        objects = entity.get("objetos", [])
        if not isinstance(objects, list):
            continue
        for index, item in enumerate(objects):
            if not isinstance(item, dict):
                continue
            components: dict[str, str] = {}
            evidence: list[dict[str, Any]] = []
            for field in item.get("campos", []):
                if not isinstance(field, dict) or field.get("id_campo") not in requested:
                    continue
                values = field.get("valores", [])
                if isinstance(values, list) and values and isinstance(values[0], str):
                    components[str(field["id_campo"])] = values[0]
                evidence.extend(_evidence(value) for value in field.get("evidencias", []) if isinstance(value, dict))
            if not components:
                continue
            try:
                normalized = _object_value(formatter, components)
            except NormalizationError:
                continue
            result.append(Normalizacion(formatter.id_formateador, formatter.nombre, formatter.campos_entrada, {name: components[name] for name in formatter.campos_entrada if name in components}, normalized, tuple(evidence), index))
    return tuple(result)


def _logger(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.normalizacion.{directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(directory / "normalizacion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def normalize_expediente_data(project_root: Path, expediente_id: str) -> ResultadoNormalizacion:
    """Aplica los formateadores vigentes y escribe una salida separada y trazable."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise NormalizationError(str(error)) from error
    source = _path(configuration, "extraccion", "extraccion_documental.json", expediente_id)
    payload = _load(source, expediente_id)
    fields = [field for field in payload.get("campos", []) if isinstance(field, dict)]
    normalizations: list[Normalizacion] = []
    warnings: list[str] = []
    no_data: list[str] = []
    formatters = _formatters(configuration)
    for formatter in formatters:
        generated: tuple[Normalizacion, ...] = ()
        if _normalizar(formatter.tipo_entrada) == "objeto":
            generated = _objects(formatter, fields)
        else:
            values = tuple(value for field in fields if _matches(formatter, field) for value in _values(field))
            if values:
                try:
                    if formatter.nombre == "Lista_Matriculas":
                        generated = (Normalizacion(formatter.id_formateador, formatter.nombre, formatter.campos_entrada, tuple(value for value, _ in values), ", ".join(value.strip() for value, _ in values), tuple(evidence for _, evidence in values)),)
                    else:
                        generated = tuple(Normalizacion(formatter.id_formateador, formatter.nombre, formatter.campos_entrada, value, _scalar(formatter, value), (evidence,)) for value, evidence in values if _formatter_applies(formatter, value))
                except NormalizationError as error:
                    warnings.append(f"{formatter.id_formateador}: {error}")
        if generated:
            normalizations.extend(generated)
        else:
            no_data.append(formatter.id_formateador)
    summary = ResumenNormalizacion(len(formatters), len({item.id_formateador for item in normalizations}), len(normalizations), tuple(no_data))
    provisional = ResultadoNormalizacion(expediente_id, tuple(normalizations), tuple(warnings), "", summary)
    target = _path(configuration, "normalizacion", "normalizacion_documental.json", expediente_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise NormalizationError("El archivo de normalización sale de la ruta de salida configurada") from error
    target.write_text(json.dumps({"id_expediente": expediente_id, "origen_extraccion": source.relative_to(configuration.project_root).as_posix(), "normalizaciones": [asdict(item) for item in normalizations], "advertencias_configuracion": warnings, "resumen": asdict(summary)}, ensure_ascii=False, indent=2), encoding="utf-8")
    logger = _logger(configuration.route("logs"))
    for item in normalizations:
        logger.info("NORMALIZACION | %s | %s", item.id_formateador, item.nombre_formateador)
    for warning in warnings:
        logger.warning("NORMALIZACION | %s", warning)
    logger.info("NORMALIZACION COMPLETADA | %s | %s formateador(es) | %s valor(es)", expediente_id, summary.total_formateadores_aplicados, summary.total_normalizaciones)
    return ResultadoNormalizacion(expediente_id, tuple(normalizations), tuple(warnings), target.relative_to(configuration.project_root).as_posix(), summary)
