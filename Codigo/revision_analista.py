"""Segundo análisis humano y control previo a la generación documental."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigurationError, ProjectConfiguration, load_configuration


class AnalystReviewError(ValueError):
    """La revisión humana no puede registrarse o no autoriza la siguiente fase."""


@dataclass(frozen=True)
class RevisionAnalista:
    id_expediente: str
    resultado_preliminar: str
    estado: str
    observacion: str
    fecha_revision: str | None
    generacion_habilitada: bool
    archivo_salida: str


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


def _save_review(
    configuration: ProjectConfiguration,
    expediente_id: str,
    result: str,
    state: str,
    observation: str,
    review_date: str | None,
) -> RevisionAnalista:
    path = _review_path(configuration, expediente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    review = RevisionAnalista(
        expediente_id,
        result,
        state,
        observation,
        review_date,
        state == _review_state(configuration, "estado_habilita_generacion", "Confirmado"),
        path.relative_to(configuration.project_root).as_posix(),
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
        configuration, expediente_id, preliminary_result, initial_state, "", None
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
        )
    except KeyError as error:
        raise AnalystReviewError("La revisión del analista está incompleta") from error


def record_analyst_review(
    project_root: Path,
    expediente_id: str,
    state: str,
    observation: str = "",
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
    return _save_review(
        configuration,
        expediente_id,
        preliminary_result,
        state,
        cleaned_observation,
        datetime.now(timezone.utc).isoformat(),
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
