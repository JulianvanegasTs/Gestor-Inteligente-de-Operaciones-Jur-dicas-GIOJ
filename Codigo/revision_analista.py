"""Segundo análisis humano y control previo a la generación documental."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .validacion import ValidationError, load_business_rules


class AnalystReviewError(ValueError):
    """La revisión humana no puede registrarse o no autoriza la siguiente fase."""


@dataclass(frozen=True)
class RevisionValidacionAnalista:
    id_regla: str
    estado_sistema: str
    estado_revision: str
    observacion: str = ""
    descripcion: str = ""


@dataclass(frozen=True)
class RevisionAnalista:
    id_expediente: str
    resultado_preliminar: str
    estado: str
    observacion: str
    fecha_revision: str | None
    generacion_habilitada: bool
    archivo_salida: str
    validaciones: tuple[RevisionValidacionAnalista, ...] = ()
    total_validaciones: int = 0
    validaciones_pendientes: int = 0


@dataclass(frozen=True)
class AutorizacionGeneracion:
    id_expediente: str
    resultado_confirmado: str
    plantilla: str
    estado_revision: str


def _configured_filename(
    configuration: ProjectConfiguration,
    section: str,
    default: str,
) -> str:
    settings = configuration.values.get(section, {})
    filename = str(settings.get("archivo_salida", default)) if isinstance(settings, dict) else default
    if Path(filename).name != filename:
        raise AnalystReviewError(f"El archivo de {section} debe ser un nombre de archivo")
    return filename


def _review_settings(configuration: ProjectConfiguration) -> dict[str, Any]:
    settings = configuration.values.get("revision_analista", {})
    return settings if isinstance(settings, dict) else {}


def _review_state(
    configuration: ProjectConfiguration,
    key: str,
    default: str,
) -> str:
    return str(_review_settings(configuration).get(key, default))


def _output_directory(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    if not isinstance(expediente_id, str) or not expediente_id.strip():
        raise AnalystReviewError("El identificador del expediente es obligatorio")
    candidate = Path(expediente_id.strip())
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {".", ".."}:
        raise AnalystReviewError("El identificador del expediente no es válido")
    output_root = configuration.route("salida").resolve()
    directory = (output_root / candidate).resolve()
    try:
        directory.relative_to(output_root)
    except ValueError as error:
        raise AnalystReviewError("El expediente sale de la ruta de salida configurada") from error
    return directory


def _review_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return _output_directory(configuration, expediente_id) / _configured_filename(
        configuration, "revision_analista", "revision_analista.json"
    )


def _legal_result_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return _output_directory(configuration, expediente_id) / _configured_filename(
        configuration, "motor_juridico", "resultado_juridico.json"
    )


def _load_json(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise AnalystReviewError(f"No se encontró {description}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalystReviewError(f"No fue posible leer {description}: {error}") from error
    if not isinstance(payload, dict):
        raise AnalystReviewError(f"{description.capitalize()} no contiene un objeto válido")
    return payload


def _configuration(project_root: Path) -> ProjectConfiguration:
    try:
        return load_configuration(project_root)
    except ConfigurationError as error:
        raise AnalystReviewError(str(error)) from error


def _preliminary_result(configuration: ProjectConfiguration, expediente_id: str) -> str:
    payload = _load_json(
        _legal_result_path(configuration, expediente_id), "el resultado jurídico preliminar"
    )
    if payload.get("id_expediente") != expediente_id:
        raise AnalystReviewError("El resultado jurídico no corresponde al expediente seleccionado")
    result = payload.get("resultado_preliminar") or payload.get("resultado")
    if result not in {"Conformidad", "No Conformidad"}:
        raise AnalystReviewError("El resultado jurídico preliminar no es válido")
    return str(result)


def _legal_validations(
    configuration: ProjectConfiguration, expediente_id: str
) -> tuple[RevisionValidacionAnalista, ...]:
    try:
        payload = _load_json(
            _legal_result_path(configuration, expediente_id), "el resultado jurídico preliminar"
        )
    except AnalystReviewError:
        # Compatibilidad para integraciones que entregan el resultado en memoria;
        # el flujo productivo siempre persiste el motor antes de esta fase.
        return ()
    evaluations = payload.get("evaluaciones_reglas", [])
    try:
        rule_names = {
            rule.id_regla: str(rule.criterios.get("Nombre_Regla") or rule.tipo_regla)
            .replace("Escritura_Firma", "escritura sometida a firma")
            .replace("_", " ")
            for rule in load_business_rules(configuration)
        }
    except ValidationError:
        rule_names = {}
    result: list[RevisionValidacionAnalista] = []
    for item in evaluations if isinstance(evaluations, list) else []:
        if not isinstance(item, dict) or not item.get("id_regla"):
            continue
        system_state = str(item.get("resultado_validacion", "No existe información"))
        review_state = "Confirmada" if system_state == "No aplica" else "Pendiente"
        result.append(RevisionValidacionAnalista(
            str(item["id_regla"]),
            system_state,
            review_state,
            "",
            rule_names.get(
                str(item["id_regla"]),
                str(item.get("tipo_regla") or "Comprobación jurídica").replace("_", " "),
            ),
        ))
    return tuple(result)


def _save_review(
    configuration: ProjectConfiguration,
    expediente_id: str,
    result: str,
    state: str,
    observation: str,
    review_date: str | None,
    validations: tuple[RevisionValidacionAnalista, ...] = (),
) -> RevisionAnalista:
    path = _review_path(configuration, expediente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = sum(item.estado_revision == "Pendiente" for item in validations)
    review = RevisionAnalista(
        expediente_id,
        result,
        state,
        observation,
        review_date,
        state == _review_state(configuration, "estado_habilita_generacion", "Confirmado"),
        path.relative_to(configuration.project_root).as_posix(),
        validations,
        len(validations),
        pending,
    )
    path.write_text(json.dumps(asdict(review), ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def initialize_analyst_review(
    project_root: Path,
    expediente_id: str,
    preliminary_result: str,
) -> RevisionAnalista:
    """Restablece la revisión a Pendiente cada vez que se ejecuta un nuevo análisis."""
    if preliminary_result not in {"Conformidad", "No Conformidad"}:
        raise AnalystReviewError("El resultado jurídico preliminar no es válido")
    configuration = _configuration(project_root)
    initial_state = _review_state(configuration, "estado_inicial", "Pendiente")
    return _save_review(
        configuration,
        expediente_id,
        preliminary_result,
        initial_state,
        "",
        None,
        _legal_validations(configuration, expediente_id),
    )


def load_analyst_review(project_root: Path, expediente_id: str) -> RevisionAnalista:
    configuration = _configuration(project_root)
    path = _review_path(configuration, expediente_id)
    payload = _load_json(path, "la revisión del analista")
    try:
        return RevisionAnalista(
            str(payload["id_expediente"]),
            str(payload["resultado_preliminar"]),
            str(payload["estado"]),
            str(payload.get("observacion", "")),
            str(payload["fecha_revision"]) if payload.get("fecha_revision") else None,
            bool(payload["generacion_habilitada"]),
            path.relative_to(configuration.project_root).as_posix(),
            tuple(
                RevisionValidacionAnalista(
                    str(item["id_regla"]),
                    str(item.get("estado_sistema", "")),
                    str(item.get("estado_revision", "Pendiente")),
                    str(item.get("observacion", "")),
                    str(item.get("descripcion", "Comprobación jurídica")),
                )
                for item in payload.get("validaciones", [])
                if isinstance(item, dict) and item.get("id_regla")
            ),
            int(payload.get("total_validaciones", len(payload.get("validaciones", [])))),
            int(payload.get("validaciones_pendientes", 0)),
        )
    except KeyError as error:
        raise AnalystReviewError("La revisión del analista está incompleta") from error


def record_analyst_review(
    project_root: Path,
    expediente_id: str,
    state: str,
    observation: str = "",
    validations: list[dict[str, Any]] | tuple[RevisionValidacionAnalista, ...] | None = None,
) -> RevisionAnalista:
    """Registra la confirmación o el rechazo emitido por el analista."""
    configuration = _configuration(project_root)
    settings = _review_settings(configuration)
    allowed_states = tuple(
        str(item)
        for item in settings.get(
            "estados_permitidos", ["Pendiente", "Confirmado", "Rechazado"]
        )
    )
    initial_state = _review_state(configuration, "estado_inicial", "Pendiente")
    decisions = tuple(item for item in allowed_states if item != initial_state)
    if state not in decisions:
        raise AnalystReviewError(
            f"La decisión debe corresponder a uno de estos estados: {', '.join(decisions)}"
        )
    cleaned_observation = observation.strip()
    reject_state = _review_state(configuration, "estado_rechazo", "Rechazado")
    observation_required = bool(
        settings.get("observacion_obligatoria_al_rechazar", True)
    )
    if state == reject_state and observation_required and not cleaned_observation:
        raise AnalystReviewError("La observación es obligatoria cuando el análisis se rechaza")
    preliminary_result = _preliminary_result(configuration, expediente_id)
    try:
        current = load_analyst_review(project_root, expediente_id)
    except AnalystReviewError:
        current = RevisionAnalista(
            expediente_id, preliminary_result, initial_state, "", None, False, ""
        )
    review_by_id = {item.id_regla: item for item in current.validaciones}
    if validations is not None:
        allowed_individual = {
            str(item) for item in settings.get(
                "estados_revision_validacion", ["Pendiente", "Confirmada", "Observada"]
            )
        }
        for raw in validations:
            item = raw if isinstance(raw, RevisionValidacionAnalista) else None
            if item is None and isinstance(raw, dict):
                rule_id = str(raw.get("id_regla", "")).strip()
                review_state = str(raw.get("estado_revision", "")).strip()
                note = str(raw.get("observacion", "")).strip()
                previous = review_by_id.get(rule_id)
                if not previous:
                    raise AnalystReviewError(
                        f"La validación {rule_id or '(sin ID)'} no pertenece al análisis"
                    )
                item = RevisionValidacionAnalista(
                    rule_id,
                    previous.estado_sistema,
                    review_state,
                    note,
                    previous.descripcion,
                )
            if item is None or item.estado_revision not in allowed_individual:
                raise AnalystReviewError("La revisión individual contiene un estado no permitido")
            if item.estado_revision == "Observada" and not item.observacion.strip():
                raise AnalystReviewError(f"La observación es obligatoria para {item.id_regla}")
            review_by_id[item.id_regla] = item
    individual = tuple(
        review_by_id[item.id_regla] for item in current.validaciones
    )
    individual_required = bool(settings.get("revision_individual_obligatoria", False))
    pending = [item.id_regla for item in individual if item.estado_revision == "Pendiente"]
    if individual_required and pending:
        raise AnalystReviewError(
            f"Revise individualmente las {len(pending)} comprobación(es) pendientes antes de decidir"
        )
    return _save_review(
        configuration,
        expediente_id,
        preliminary_result,
        state,
        cleaned_observation,
        datetime.now(timezone.utc).isoformat(),
        individual,
    )


def authorize_document_generation(
    project_root: Path,
    expediente_id: str,
) -> AutorizacionGeneracion:
    """Verifica la autorización; no implementa las fases posteriores Word/PDF."""
    configuration = _configuration(project_root)
    review = load_analyst_review(project_root, expediente_id)
    authorized_state = _review_state(
        configuration, "estado_habilita_generacion", "Confirmado"
    )
    if review.estado != authorized_state or not review.generacion_habilitada:
        raise AnalystReviewError(
            "La generación documental requiere que el analista confirme previamente el análisis"
        )
    key = (
        "plantilla_conformidad"
        if review.resultado_preliminar == "Conformidad"
        else "plantilla_no_conformidad"
    )
    try:
        template_name = str(configuration.values["archivos"][key])
    except (KeyError, TypeError) as error:
        raise AnalystReviewError("La plantilla correspondiente no está configurada") from error
    template = configuration.route("plantillas") / template_name
    if not template.is_file():
        raise AnalystReviewError(f"No se encontró la plantilla oficial {template_name}")
    return AutorizacionGeneracion(
        expediente_id,
        review.resultado_preliminar,
        template.relative_to(configuration.project_root).as_posix(),
        review.estado,
    )
