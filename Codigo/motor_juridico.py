"""Consolidación jurídica de las reglas definidas en 04_Reglas_Negocio."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .clasificacion import _normalizar
from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .extraccion import CampoExtraccion, ExtractionError, load_extraction_fields
from .validacion import ReglaNegocio, load_business_rules


class LegalEngineError(ValueError):
    """La arquitectura o las validaciones no permiten emitir un resultado jurídico."""


@dataclass(frozen=True)
class EvaluacionReglaJuridica:
    id_regla: str
    tipo_regla: str
    fuente_regla: str
    estado_configurado: str | None
    resultado_validacion: str
    seleccionada: bool
    efecto: str
    observacion: str


@dataclass(frozen=True)
class ResultadoTipoRegla:
    tipo_regla: str
    estado: str
    reglas_definidas: int
    reglas_coincidentes: tuple[str, ...]
    estados_configurados: tuple[str, ...]
    observacion: str


@dataclass(frozen=True)
class ObservacionJuridica:
    numero: int
    tipo_regla: str
    estado: str
    reglas_relacionadas: tuple[str, ...]
    detalle: str


@dataclass(frozen=True)
class ResumenMotorJuridico:
    total_reglas_definidas: int
    total_reglas_evaluadas: int
    total_tipos_regla: int
    tipos_cumple: int
    tipos_no_cumple: int
    tipos_no_existe_informacion: int
    tipos_no_aplica: int


@dataclass(frozen=True)
class RegistroTrazabilidad:
    id_regla: str
    documento: str
    pagina: int
    campo: str
    valor_encontrado: str
    valor_esperado: str
    resultado: str
    observacion: str
    estado_validacion: str = ""


@dataclass(frozen=True)
class RegistroCampoObligatorio:
    """Matriz visible de un dato obligatorio contrastado con Escritura_Firma."""

    datos: str
    valor_encontrado: str
    documento_validado: str
    pagina: int
    resultado: str


@dataclass(frozen=True)
class ResultadoTrazabilidad:
    sintesis_dictamen: str
    registros: tuple[RegistroTrazabilidad, ...]
    inconsistencias: tuple[RegistroTrazabilidad, ...]
    campos_obligatorios: tuple[RegistroCampoObligatorio, ...] = ()


@dataclass(frozen=True)
class ResultadoMotorJuridico:
    id_expediente: str
    resultado: str
    evaluaciones_reglas: tuple[EvaluacionReglaJuridica, ...]
    resultados_por_tipo: tuple[ResultadoTipoRegla, ...]
    observaciones: tuple[ObservacionJuridica, ...]
    archivo_salida: str
    resumen: ResumenMotorJuridico
    concepto_juridico: str = ""
    trazabilidad: ResultadoTrazabilidad | None = None


_VALIDATION_STATES = {"Cumple", "No cumple", "No existe información", "No aplica"}


def _configured_filename(configuration: ProjectConfiguration, section: str, default: str) -> str:
    settings = configuration.values.get(section, {})
    filename = str(settings.get("archivo_salida", default)) if isinstance(settings, dict) else default
    if Path(filename).name != filename:
        raise LegalEngineError(f"El archivo de {section} debe ser un nombre de archivo")
    return filename


def _expediente_output_directory(
    configuration: ProjectConfiguration, expediente_id: str
) -> Path:
    if not isinstance(expediente_id, str) or not expediente_id.strip():
        raise LegalEngineError("El identificador del expediente es obligatorio")
    candidate = Path(expediente_id.strip())
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {".", ".."}:
        raise LegalEngineError("El identificador del expediente no es válido")
    output_root = configuration.route("salida").resolve()
    directory = (output_root / candidate).resolve()
    try:
        directory.relative_to(output_root)
    except ValueError as error:
        raise LegalEngineError("El expediente sale de la ruta de salida configurada") from error
    return directory


def _validation_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return _expediente_output_directory(configuration, expediente_id) / _configured_filename(
        configuration, "validacion", "validaciones_documentales.json"
    )


def _output_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return _expediente_output_directory(configuration, expediente_id) / _configured_filename(
        configuration, "motor_juridico", "resultado_juridico.json"
    )


def _load_validations(
    configuration: ProjectConfiguration,
    expediente_id: str,
    rules: tuple[ReglaNegocio, ...],
) -> tuple[Path, dict[str, dict[str, Any]]]:
    source = _validation_path(configuration, expediente_id)
    if not source.is_file():
        raise LegalEngineError(
            "No se encontró el resultado de validaciones; ejecute primero las fases anteriores"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LegalEngineError(f"No fue posible leer el resultado de validaciones: {error}") from error
    sheet_name = str(configuration.values.get("hojas", {}).get("reglas", ""))
    if not isinstance(payload, dict) or payload.get("id_expediente") != expediente_id:
        raise LegalEngineError("El resultado de validaciones no corresponde al expediente seleccionado")
    if payload.get("origen_reglas") != sheet_name:
        raise LegalEngineError("El resultado de validaciones no proviene de la hoja de reglas configurada")
    raw_validations = payload.get("validaciones")
    if not isinstance(raw_validations, list):
        raise LegalEngineError("El resultado de validaciones no contiene una lista válida")

    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in raw_validations:
        if not isinstance(item, dict) or not isinstance(item.get("id_regla"), str):
            raise LegalEngineError("Existe una validación sin ID_Regla válido")
        rule_id = item["id_regla"]
        if rule_id in indexed:
            duplicates.append(rule_id)
        indexed[rule_id] = item
    if duplicates:
        raise LegalEngineError("El resultado contiene validaciones duplicadas: " + ", ".join(duplicates))

    expected = {rule.id_regla for rule in rules}
    missing = sorted(expected - indexed.keys())
    unknown = sorted(indexed.keys() - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("faltan " + ", ".join(missing))
        if unknown:
            details.append("sobran " + ", ".join(unknown))
        raise LegalEngineError(
            "Las validaciones no cubren exactamente 04_Reglas_Negocio: " + "; ".join(details)
        )
    invalid_states = sorted(
        rule_id for rule_id, item in indexed.items() if item.get("estado") not in _VALIDATION_STATES
    )
    if invalid_states:
        raise LegalEngineError(
            "Existen reglas con estado de validación no permitido: " + ", ".join(invalid_states)
        )
    return source, indexed


def _rule_status(rule: ReglaNegocio) -> str | None:
    for column, value in rule.criterios.items():
        if _normalizar(column) == "estado":
            return value
    return None


def _is_enabling(rule: ReglaNegocio) -> bool:
    """Interpreta el Estado de la fila; una regla sin Estado no añade una restricción."""
    status = _rule_status(rule)
    return status is None or _normalizar(status) == "vigente"


def _comparison_type(rule: ReglaNegocio) -> str:
    return next(
        (value for column, value in rule.criterios.items() if _normalizar(column) == "tipo comparacion"),
        "",
    )


def _evaluate_rule(rule: ReglaNegocio, validation: dict[str, Any]) -> EvaluacionReglaJuridica:
    validation_state = str(validation["estado"])
    selected = validation_state == "Cumple"
    configured_status = _rule_status(rule)
    if selected and _is_enabling(rule):
        effect = "Coincidencia habilitante"
        observation = "La validación coincide con una alternativa vigente de la arquitectura."
    elif selected:
        effect = "Coincidencia no habilitante"
        observation = "La validación coincide con una alternativa cuyo Estado no es Vigente."
    elif validation_state == "No aplica":
        effect = "No aplica"
        observation = "La validación determinó que la alternativa no aplica al expediente."
    elif validation_state == "No existe información":
        effect = "Sin evidencia suficiente"
        observation = "No existe información suficiente para seleccionar esta alternativa."
    else:
        effect = "Alternativa descartada"
        observation = "Los datos del expediente no coinciden con esta alternativa."
    return EvaluacionReglaJuridica(
        rule.id_regla,
        rule.tipo_regla,
        rule.fuente_regla,
        configured_status,
        validation_state,
        selected,
        effect,
        observation,
    )


def _evaluate_type(
    rule_type: str,
    rules: tuple[ReglaNegocio, ...],
    validations: dict[str, dict[str, Any]],
) -> ResultadoTipoRegla:
    selected = tuple(rule for rule in rules if validations[rule.id_regla]["estado"] == "Cumple")
    selected_ids = tuple(rule.id_regla for rule in selected)
    configured_states = tuple(dict.fromkeys(status for rule in selected if (status := _rule_status(rule))))
    if any(_comparison_type(rule) for rule in rules):
        states = {str(validations[rule.id_regla]["estado"]) for rule in rules}
        if "No cumple" in states:
            state = "No cumple"
            observation = "Al menos un control obligatorio de este grupo no fue validado."
        elif "No existe información" in states:
            state = "No existe información"
            observation = "Falta evidencia documental para completar al menos un control de este grupo."
        elif states <= {"No aplica"}:
            state = "No aplica"
            observation = "Todos los controles de este grupo fueron declarados no aplicables."
        else:
            state = "Cumple"
            observation = "Todos los controles aplicables de este grupo fueron validados."
        return ResultadoTipoRegla(rule_type, state, len(rules), selected_ids, configured_states, observation)
    if selected:
        if all(_is_enabling(rule) for rule in selected):
            state = "Cumple"
            observation = "Existe al menos una alternativa coincidente y todas las coincidencias están vigentes."
        else:
            state = "No cumple"
            observation = (
                "Existe una coincidencia con Estado distinto de Vigente; el expediente no puede declararse conforme."
            )
    else:
        states = {str(validations[rule.id_regla]["estado"]) for rule in rules}
        if states == {"No aplica"}:
            state = "No aplica"
            observation = "Todas las alternativas de este tipo fueron declaradas no aplicables."
        elif "No cumple" in states:
            state = "No cumple"
            observation = "Ninguna alternativa de la arquitectura coincide con los datos del expediente."
        else:
            state = "No existe información"
            observation = "No existe evidencia suficiente para seleccionar una alternativa de la arquitectura."
    return ResultadoTipoRegla(
        rule_type,
        state,
        len(rules),
        selected_ids,
        configured_states,
        observation,
    )


def _legal_concept(result: str, validations: dict[str, dict[str, Any]]) -> str:
    failed = [
        item
        for rule_id, item in validations.items()
        if rule_id != "CON-001"
        and item.get("estado") in {"No cumple", "No existe información"}
    ]
    if not failed:
        return (
            "El expediente fue validado contra los campos obligatorios, la estructura de Minuta_hipoteca y "
            "las reglas de poderes aplicables. No se identificaron hallazgos que impidan la conformidad. "
            "El resultado preliminar es Conformidad y queda pendiente de confirmación por el analista jurídico."
        )
    details = " ".join(
        f"{index}. {item.get('id_regla', 'Regla no identificada')} ({item.get('estado')}): "
        f"{item.get('observacion') or 'requiere revisión de la evidencia registrada.'}"
        for index, item in enumerate(failed, 1)
    )
    return (
        f"El análisis concluye {result} preliminar al registrar {len(failed)} validación(es) "
        f"adversa(s) o sin evidencia suficiente. Hallazgos que requieren corrección: {details} "
        "El analista jurídico debe revisar la evidencia, confirmar o rechazar el análisis y su "
        "decisión no puede ser sustituida por este concepto."
    )


def _as_trace_text(value: Any, fallback: str) -> str:
    if isinstance(value, (list, tuple)):
        text = " | ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip() if value is not None else ""
    return text or fallback


def _trace_page(comparison: dict[str, Any]) -> int:
    candidates = [comparison.get("pagina_validada")]
    origin_pages = comparison.get("pagina_origen")
    if isinstance(origin_pages, (list, tuple)) and origin_pages:
        candidates.append(origin_pages[0])
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, (int, float)) and int(candidate) > 0:
            return int(candidate)
        if isinstance(candidate, str) and candidate.strip().isdigit() and int(candidate.strip()) > 0:
            return int(candidate.strip())
    return 0


def _trace_document(comparison: dict[str, Any]) -> str:
    validated = comparison.get("documento_validado")
    if isinstance(validated, str) and validated.strip():
        return validated.strip()
    origins = comparison.get("documento_origen")
    if isinstance(origins, (list, tuple)) and origins:
        return _as_trace_text(origins[0], "No identificado")
    return _as_trace_text(comparison.get("documento_destino"), "No identificado")


def _trace_field(rule: ReglaNegocio, comparison: dict[str, Any]) -> str:
    field = comparison.get("campo")
    if isinstance(field, str) and field.strip():
        return field.strip()
    return next(
        (
            value
            for column, value in rule.criterios.items()
            if _normalizar(column) == _normalizar("ID_Campo_Clausula")
        ),
        rule.id_regla,
    )


def _criterion(rule: ReglaNegocio, name: str, fallback: str = "") -> str:
    normalized_name = _normalizar(name)
    return next(
        (
            value
            for column, value in rule.criterios.items()
            if _normalizar(column) == normalized_name
        ),
        fallback,
    )


def _compared_page(comparison: dict[str, Any]) -> int:
    candidate = comparison.get("pagina_comparada")
    if isinstance(candidate, bool):
        return 0
    if isinstance(candidate, (int, float)) and int(candidate) > 0:
        return int(candidate)
    if isinstance(candidate, str) and candidate.strip().isdigit() and int(candidate.strip()) > 0:
        return int(candidate.strip())
    return 0


def _document_name(value: Any, fallback: str) -> str:
    """Reduce la referencia trazable al nombre visible del documento original."""
    document = _as_trace_text(value, fallback).replace("\\", "/")
    return document.rsplit("/", 1)[-1]


def _mandatory_field_traceability(
    fields: tuple[CampoExtraccion, ...],
    rules: tuple[ReglaNegocio, ...],
    validations: dict[str, dict[str, Any]],
) -> tuple[RegistroCampoObligatorio, ...]:
    """Construye la matriz visible en el orden oficial de 01_Campos_Extraccion."""
    mandatory_fields = tuple(
        field for field in fields if _normalizar(field.obligatorio or "") == "si"
    )
    mandatory_rules = {
        _criterion(rule, "ID_Campo_Clausula"): rule
        for rule in rules
        if _normalizar(rule.tipo_regla) in {"campo obligatorio", "campo_obligatorio"}
        and _criterion(rule, "ID_Campo_Clausula")
    }
    records: list[RegistroCampoObligatorio] = []
    for field in mandatory_fields:
        rule = mandatory_rules.get(field.id_campo)
        validation = validations.get(rule.id_regla, {}) if rule else {}
        raw_comparisons = validation.get("comparaciones")
        comparison = (
            raw_comparisons[0]
            if isinstance(raw_comparisons, list)
            and raw_comparisons
            and isinstance(raw_comparisons[0], dict)
            else {}
        )
        validation_state = str(comparison.get("estado") or validation.get("estado") or "")
        records.append(
            RegistroCampoObligatorio(
                datos=field.campo or field.id_campo,
                valor_encontrado=_as_trace_text(
                    comparison.get("valor_esperado"),
                    "No se encontró información",
                ),
                documento_validado=_document_name(
                    comparison.get("documento_comparado"),
                    _criterion(rule, "Documento_Comparado", "No identificado")
                    if rule
                    else "No identificado",
                ),
                pagina=_compared_page(comparison),
                resultado=(
                    "Coincide con Escritura_Firma"
                    if validation_state == "Cumple"
                    else "No coincide con Escritura_Firma"
                ),
            )
        )
    return tuple(records)


def _build_traceability(
    result: str,
    rules: tuple[ReglaNegocio, ...],
    validations: dict[str, dict[str, Any]],
    fields: tuple[CampoExtraccion, ...] = (),
) -> ResultadoTrazabilidad:
    """Consolida todas las decisiones ya evidenciadas por las validaciones."""
    records: list[RegistroTrazabilidad] = []
    for rule in rules:
        validation = validations[rule.id_regla]
        state = str(validation.get("estado", "No existe información"))
        raw_comparisons = validation.get("comparaciones")
        comparisons = raw_comparisons if isinstance(raw_comparisons, list) and raw_comparisons else [{}]
        for raw_comparison in comparisons:
            comparison = raw_comparison if isinstance(raw_comparison, dict) else {}
            comparison_state = str(comparison.get("estado") or state)
            records.append(
                RegistroTrazabilidad(
                    id_regla=rule.id_regla,
                    documento=_trace_document(comparison),
                    pagina=_trace_page(comparison),
                    campo=_trace_field(rule, comparison),
                    valor_encontrado=_as_trace_text(
                        comparison.get("valor_encontrado"),
                        "No se encontró información",
                    ),
                    valor_esperado=_as_trace_text(
                        comparison.get("valor_esperado"),
                        "No disponible",
                    ),
                    resultado=(
                        "No coincide"
                        if comparison_state in {"No cumple", "No existe información"}
                        else "Coincide"
                    ),
                    observacion=_as_trace_text(
                        comparison.get("observacion"),
                        _as_trace_text(validation.get("observacion"), "Sin observación registrada"),
                    ),
                    estado_validacion=state,
                )
            )
    inconsistencies = tuple(record for record in records if record.resultado == "No coincide")
    if inconsistencies:
        synthesis = (
            "Examinado el acervo documental y confrontada la escritura de firma con las fuentes "
            f"rectoras del análisis, se identificaron {len(inconsistencies)} inconsistencia(s) que "
            "afectan la correspondencia jurídica del instrumento. En mérito de lo expuesto, se "
            f"propone dictamen de {result.lower()}, sujeto a la revisión y al criterio profesional "
            "del analista jurídico."
        )
    else:
        synthesis = (
            "Examinado el acervo documental y confrontada la escritura de firma con las fuentes "
            "rectoras del análisis, se colige que las validaciones aplicables guardan "
            "correspondencia. En mérito de lo expuesto, se propone dictamen de conformidad, sujeto "
            "a la revisión y al criterio profesional del analista jurídico."
        )
    mandatory_fields = _mandatory_field_traceability(fields, rules, validations)
    return ResultadoTrazabilidad(synthesis, tuple(records), inconsistencies, mandatory_fields)


def _logger(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.motor_juridico.{directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(directory / "motor_juridico.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def apply_legal_engine(project_root: Path, expediente_id: str) -> ResultadoMotorJuridico:
    """Evalúa todas las reglas de Excel y determina Conformidad o No Conformidad."""
    try:
        configuration = load_configuration(project_root)
        rules = load_business_rules(configuration)
        fields = load_extraction_fields(configuration)
    except (ConfigurationError, ExtractionError, ValueError) as error:
        raise LegalEngineError(str(error)) from error
    source, validations = _load_validations(configuration, expediente_id, rules)

    evaluations = tuple(_evaluate_rule(rule, validations[rule.id_regla]) for rule in rules)
    types = tuple(dict.fromkeys(rule.tipo_regla for rule in rules))
    results_by_type = tuple(
        _evaluate_type(
            rule_type,
            tuple(rule for rule in rules if rule.tipo_regla == rule_type),
            validations,
        )
        for rule_type in types
    )
    consolidation = validations.get("CON-001")
    result = (
        "Conformidad"
        if (
            consolidation.get("estado") == "Cumple"
            if consolidation is not None
            else all(item.estado in {"Cumple", "No aplica"} for item in results_by_type)
        )
        else "No Conformidad"
    )
    observations = tuple(
        ObservacionJuridica(
            number,
            item.tipo_regla,
            item.estado,
            item.reglas_coincidentes
            or tuple(rule.id_regla for rule in rules if rule.tipo_regla == item.tipo_regla),
            item.observacion,
        )
        for number, item in enumerate(
            (item for item in results_by_type if item.estado not in {"Cumple", "No aplica"}), 1
        )
    )
    summary = ResumenMotorJuridico(
        len(rules),
        len(evaluations),
        len(results_by_type),
        sum(item.estado == "Cumple" for item in results_by_type),
        sum(item.estado == "No cumple" for item in results_by_type),
        sum(item.estado == "No existe información" for item in results_by_type),
        sum(item.estado == "No aplica" for item in results_by_type),
    )
    concept = _legal_concept(result, validations)
    traceability = _build_traceability(result, rules, validations, fields)

    target = _output_path(configuration, expediente_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise LegalEngineError("El resultado jurídico sale de la ruta de salida configurada") from error
    target.write_text(
        json.dumps(
            {
                "id_expediente": expediente_id,
                "origen_reglas": str(configuration.values["hojas"]["reglas"]),
                "origen_validaciones": source.relative_to(configuration.project_root).as_posix(),
                "resultado": result,
                "resultado_preliminar": result,
                "estado_revision_analista": "Pendiente",
                "generacion_habilitada": False,
                "concepto_juridico": concept,
                "evaluaciones_reglas": [asdict(item) for item in evaluations],
                "resultados_por_tipo": [asdict(item) for item in results_by_type],
                "observaciones": [asdict(item) for item in observations],
                "resumen": asdict(summary),
                "trazabilidad": asdict(traceability),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger = _logger(configuration.route("logs"))
    for item in results_by_type:
        logger.info("MOTOR JURIDICO | %s | %s", item.tipo_regla, item.estado)
    for item in traceability.registros:
        logger.info(
            "TRAZABILIDAD | %s | %s | pagina=%s | %s",
            item.id_regla,
            item.resultado,
            item.pagina,
            item.documento,
        )
    logger.info("MOTOR JURIDICO COMPLETADO | %s | resultado_preliminar=%s", expediente_id, result)
    return ResultadoMotorJuridico(
        expediente_id,
        result,
        evaluations,
        results_by_type,
        observations,
        target.relative_to(configuration.project_root).as_posix(),
        summary,
        concept,
        traceability,
    )
