"""Motor de extracción documental definido por ``Arquitectura.xlsx``.

Esta fase no contiene campos jurídicos codificados. Lee exclusivamente las
hojas ``01_Campos_Extraccion`` y ``05_Extraccion_Documental`` para construir
las instrucciones que se aplican al texto OCR y a su clasificación previa.
Cada valor conserva la evidencia que permite a las fases posteriores ubicarlo
en el documento original.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .clasificacion import _normalizar, _read_shared_strings, _read_sheet, _worksheet_paths
from .config import ConfigurationError, ProjectConfiguration, load_configuration


class ExtractionError(ValueError):
    """Indica una entrada o arquitectura no apta para la extracción."""


@dataclass(frozen=True)
class CampoExtraccion:
    """Campo oficial de la hoja ``01_Campos_Extraccion``."""

    id_campo: str
    nivel: str
    campo_padre: str | None
    entidad: str
    campo: str
    descripcion: str | None
    tipo_dato: str | None
    catalogo_asociado: str | None
    multiples: str | None
    obligatorio: str | None
    mostrar_resultado: str | None


@dataclass(frozen=True)
class InstruccionExtraccion:
    """Instrucción oficial de la hoja ``05_Extraccion_Documental``."""

    id_extraccion: str
    id_campo: str
    prioridad: str | None
    documento_origen: str
    regla_extraccion: str | None
    regla_validacion: str | None
    permite_ocr: str | None
    puede_heredarse: str | None
    campo_destino: str | None
    observaciones: str | None


@dataclass(frozen=True)
class EvidenciaExtraccion:
    """Valor y ubicación exacta recuperados del resultado OCR."""

    valor_encontrado: str
    documento: str
    pagina: int
    metodo: str | None
    confianza: float | None
    evidencia_textual: str


@dataclass(frozen=True)
class ResultadoCampo:
    """Resultado de aplicar las instrucciones disponibles para un campo."""

    campo: CampoExtraccion
    estado: str
    instrucciones: tuple[str, ...]
    valores: tuple[EvidenciaExtraccion, ...]
    observacion: str | None


@dataclass(frozen=True)
class ResultadoExtraccion:
    """Salida estructurada y persistida del motor de extracción."""

    id_expediente: str
    campos: tuple[ResultadoCampo, ...]
    advertencias_configuracion: tuple[str, ...]
    archivo_salida: str


_ACTION_WORDS = frozenset({
    "a", "al", "contra", "con", "de", "del", "desde", "detectar", "el", "en",
    "extraer", "la", "las", "los", "por", "segun", "su", "sus", "un", "una",
    "validar", "verificar",
})
_LABEL_SEPARATOR = re.compile(r"\s*(?:[:#]|\bno\.?|n[°ºo]?\.?|-)\s*", flags=re.IGNORECASE)
_VALUE_END = re.compile(r"\s{2,}|\n", flags=re.MULTILINE)


def _value(row: dict[str, str], name: str) -> str | None:
    value = row.get(name, "").strip()
    return value or None


def _read_extraction_architecture(configuration: ProjectConfiguration) -> tuple[tuple[CampoExtraccion, ...], tuple[InstruccionExtraccion, ...]]:
    """Carga solo las dos hojas autorizadas para esta etapa."""
    try:
        names = configuration.values["hojas"]
        fields_name = str(names["campos"])
        extraction_name = str(names["extraccion"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            shared_strings = _read_shared_strings(workbook)
            paths = _worksheet_paths(workbook)
            field_rows = _read_sheet(workbook, paths[fields_name], shared_strings)
            extraction_rows = _read_sheet(workbook, paths[extraction_name], shared_strings)
    except (KeyError, OSError, zipfile.BadZipFile, ValueError) as error:
        raise ExtractionError(f"No fue posible leer las hojas de extracción autorizadas: {error}") from error
    fields = tuple(
        CampoExtraccion(
            id_campo=row["ID_Campo"].strip(),
            nivel=_value(row, "Nivel") or "",
            campo_padre=_value(row, "Campo_Padre"),
            entidad=_value(row, "Entidad") or "",
            campo=_value(row, "Campo") or "",
            descripcion=_value(row, "Descripción"),
            tipo_dato=_value(row, "Tipo_Dato"),
            catalogo_asociado=_value(row, "Catalogo_Asociado"),
            multiples=_value(row, "Múltiples"),
            obligatorio=_value(row, "Obligatorio"),
            mostrar_resultado=_value(row, "Mostrar_Resultado"),
        )
        for row in field_rows
        if _value(row, "ID_Campo")
    )
    instructions = tuple(
        InstruccionExtraccion(
            id_extraccion=row["ID_Extraccion"].strip(),
            id_campo=_value(row, "ID_Campo") or "",
            prioridad=_value(row, "Prioridad"),
            documento_origen=_value(row, "Documento_Origen") or "",
            regla_extraccion=_value(row, "Regla_Extraccion"),
            regla_validacion=_value(row, "Regla_Validacion"),
            permite_ocr=_value(row, "Permite_OCR"),
            puede_heredarse=_value(row, "Puede_Heredarse"),
            campo_destino=_value(row, "Campo_Destino"),
            observaciones=_value(row, "Observaciones"),
        )
        for row in extraction_rows
        if _value(row, "ID_Extraccion")
    )
    if not fields:
        raise ExtractionError("01_Campos_Extraccion no contiene campos definidos")
    if not instructions:
        raise ExtractionError("05_Extraccion_Documental no contiene instrucciones definidas")
    return fields, instructions


def _load_json(path: Path, subject: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExtractionError(f"No se encontró {subject}; ejecute primero la fase anterior")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExtractionError(f"No fue posible leer {subject}: {error}") from error
    if not isinstance(payload, dict):
        raise ExtractionError(f"{subject} tiene un formato inválido")
    return payload


def _ocr_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    filename = str(configuration.values.get("ocr", {}).get("archivo_salida", "texto_extraido.json"))
    if Path(filename).name != filename:
        raise ExtractionError("El archivo de salida OCR debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _classification_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return configuration.route("salida") / expediente_id / "clasificacion_documental.json"


def _output_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    settings = configuration.values.get("extraccion", {})
    filename = str(settings.get("archivo_salida", "extraccion_documental.json")) if isinstance(settings, dict) else "extraccion_documental.json"
    if Path(filename).name != filename:
        raise ExtractionError("El archivo de salida de extracción debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _source_matches(instruction: InstruccionExtraccion, document: dict[str, Any]) -> bool:
    source = _normalizar(instruction.documento_origen.replace("_", " "))
    if source == "contexto":
        return True
    source_terms = tuple(word for word in source.split() if word not in _ACTION_WORDS)
    candidates = (
        document.get("codigo_tipo_documental"),
        document.get("tipo_documental"),
    )
    return any(
        isinstance(candidate, str)
        and tuple(word for word in _normalizar(candidate.replace("_", " ")).split() if word not in _ACTION_WORDS) == source_terms
        for candidate in candidates
    )


def _instruction_phrases(field: CampoExtraccion, instruction: InstruccionExtraccion) -> tuple[str, ...]:
    """Deriva etiquetas de búsqueda de los nombres e instrucciones oficiales."""
    raw_values = (field.campo, instruction.campo_destino or "", instruction.regla_extraccion or "")
    phrases: list[str] = []
    for raw_value in raw_values:
        words = [word for word in _normalizar(raw_value.replace("[]", " ").replace("_", " ")).split() if word not in _ACTION_WORDS]
        if words:
            phrases.append(" ".join(words))
    return tuple(dict.fromkeys(phrase for phrase in phrases if len(phrase) >= 3))


def _destination_name(destination: str | None) -> str:
    """Obtiene el último segmento del destino sin modificar la definición oficial."""
    if not destination:
        return ""
    return destination.replace("[]", "").split(".")[-1].strip()


def _labelled_values(text: str, phrases: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    normalized = _normalizar(text)
    for phrase in phrases:
        position = normalized.find(phrase)
        if position < 0:
            continue
        # La evidencia se toma del texto original, por línea, para no perder su valor fuente.
        original_line = next((line.strip() for line in text.splitlines() if phrase in _normalizar(line)), "")
        if not original_line:
            continue
        phrase_match = re.search(re.escape(phrase).replace(r"\ ", r"\s+"), _normalizar(original_line), flags=re.IGNORECASE)
        if phrase_match is None:
            continue
        separator = _LABEL_SEPARATOR.match(original_line, phrase_match.end())
        suffix = original_line[separator.end():].strip() if separator else original_line[phrase_match.end():].strip(" :#.-")
        suffix = _VALUE_END.split(suffix)[0].strip(" .;,-")
        if suffix:
            values.append((suffix, original_line))
    return tuple(dict.fromkeys(values))


def _generic_typed_values(text: str, field: CampoExtraccion) -> tuple[tuple[str, str], ...]:
    """Recupera formatos explícitos cuando la instrucción no trae una etiqueta visible."""
    kind = _normalizar(field.tipo_dato or "")
    if kind == "fecha":
        pattern = re.compile(r"\b\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+de\s+\d{4}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
    elif kind == "moneda":
        pattern = re.compile(r"\$\s?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\$\s?\d+(?:,\d+)?")
    else:
        return ()
    return tuple((match.group(0).strip(), match.group(0).strip()) for match in pattern.finditer(text))


def _extract_values(field: CampoExtraccion, instruction: InstruccionExtraccion, pages: list[dict[str, Any]]) -> tuple[EvidenciaExtraccion, ...]:
    phrases = _instruction_phrases(field, instruction)
    values: list[EvidenciaExtraccion] = []
    for page in pages:
        text = page.get("texto")
        if not isinstance(text, str) or not text.strip():
            continue
        found = _labelled_values(text, phrases)
        if not found:
            found = _generic_typed_values(text, field)
        for value, context in found:
            confidence = page.get("confianza")
            values.append(EvidenciaExtraccion(
                valor_encontrado=value,
                documento=str(page.get("documento", "")),
                pagina=int(page.get("pagina", 0) or 0),
                metodo=page.get("metodo") if isinstance(page.get("metodo"), str) else None,
                confianza=float(confidence) if isinstance(confidence, (int, float)) else None,
                evidencia_textual=context,
            ))
    return tuple(dict.fromkeys(values))


def _extraction_logger(log_directory: Path) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.extraccion.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "extraccion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _write_result(configuration: ProjectConfiguration, result: ResultadoExtraccion) -> Path:
    target = _output_path(configuration, result.id_expediente)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise ExtractionError("El archivo de extracción sale de la ruta de salida configurada") from error
    payload = {
        "id_expediente": result.id_expediente,
        "campos": [
            {
                **asdict(item.campo),
                "estado": item.estado,
                "instrucciones": list(item.instrucciones),
                "valores": [asdict(value) for value in item.valores],
                "observacion": item.observacion,
            }
            for item in result.campos
        ],
        "advertencias_configuracion": list(result.advertencias_configuracion),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def extract_expediente_data(project_root: Path, expediente_id: str) -> ResultadoExtraccion:
    """Extrae todos los campos configurados y persiste sus evidencias por página."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise ExtractionError(str(error)) from error
    fields, instructions = _read_extraction_architecture(configuration)
    ocr = _load_json(_ocr_path(configuration, expediente_id), "el resultado OCR")
    classification = _load_json(_classification_path(configuration, expediente_id), "la clasificación documental")
    if ocr.get("id_expediente") != expediente_id or classification.get("id_expediente") != expediente_id:
        raise ExtractionError("Los resultados previos no corresponden al expediente seleccionado")
    pages = [item for item in ocr.get("textos", []) if isinstance(item, dict)]
    documents = [item for item in classification.get("documentos", []) if isinstance(item, dict)]
    field_ids = {field.id_campo for field in fields}
    fields_by_id = {field.id_campo: field for field in fields}
    warnings_list = [
        f"{instruction.id_extraccion}: ID_Campo {instruction.id_campo} no existe en 01_Campos_Extraccion."
        for instruction in instructions
        if instruction.id_campo not in field_ids
    ]
    warnings_list.extend(
        f"{instruction.id_extraccion}: Campo_Destino {instruction.campo_destino} no coincide con el campo {field.campo} de {field.id_campo}."
        for instruction in instructions
        for field in (fields_by_id.get(instruction.id_campo),)
        if field is not None
        and _destination_name(instruction.campo_destino)
        and _normalizar(_destination_name(instruction.campo_destino)) != _normalizar(field.campo)
    )
    warnings = tuple(warnings_list)
    pages_by_document: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        document = page.get("documento")
        if isinstance(document, str):
            pages_by_document.setdefault(document, []).append(page)
    results: list[ResultadoCampo] = []
    for field in fields:
        field_instructions = tuple(item for item in instructions if item.id_campo == field.id_campo)
        evidences: list[EvidenciaExtraccion] = []
        applicable = 0
        for instruction in field_instructions:
            for document in documents:
                if not _source_matches(instruction, document):
                    continue
                applicable += 1
                source_pages = pages_by_document.get(str(document.get("documento", "")), [])
                evidences.extend(_extract_values(field, instruction, source_pages))
        unique_evidences = tuple(dict.fromkeys(evidences))
        if unique_evidences:
            status, observation = "Extraído", None
        elif not field_instructions:
            status, observation = "No existe información", "El campo no tiene una instrucción de extracción en 05_Extraccion_Documental."
        elif not applicable:
            status, observation = "No existe información", "No se identificó un documento correspondiente al origen configurado."
        else:
            status, observation = "No existe información", "No se encontró un valor con la evidencia disponible."
        results.append(ResultadoCampo(field, status, tuple(item.id_extraccion for item in field_instructions), unique_evidences, observation))
    provisional = ResultadoExtraccion(expediente_id, tuple(results), warnings, "")
    output = _write_result(configuration, provisional)
    logger = _extraction_logger(configuration.route("logs"))
    for result in results:
        logger.info("EXTRACCION CAMPO | %s | %s | %s evidencia(s)", result.campo.id_campo, result.estado, len(result.valores))
    for warning in warnings:
        logger.warning("ARQUITECTURA EXTRACCION | %s", warning)
    logger.info("EXTRACCION COMPLETADA | %s | %s campo(s)", expediente_id, len(results))
    return ResultadoExtraccion(expediente_id, tuple(results), warnings, output.relative_to(configuration.project_root).as_posix())
