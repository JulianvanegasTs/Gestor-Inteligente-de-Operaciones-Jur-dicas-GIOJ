"""Servidor local que conecta la interfaz oficial con el motor de GIOJ."""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
from dataclasses import asdict
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from .bootstrap import StartupReport, initialize_project
from .clasificacion import ClassificationError, classify_expediente_documents
from .config import ConfigurationError, load_configuration
from .extraccion import ExtractionError, extract_expediente_data
from .generacion_documental import DocumentGenerationError, generate_official_document
from .expediente import ArchivoSeleccionado, ExpedienteError, create_selected_file, list_expedientes, read_expediente
from .motor_juridico import LegalEngineError, apply_legal_engine
from .normalizacion import NormalizationError, normalize_expediente_data
from .ocr import OCRExtractionError, extract_expediente_text, extract_selected_files_text
from .revision_analista import (
    AnalystReviewError,
    initialize_analyst_review,
    load_analyst_review,
    record_analyst_review,
)
from .segmentacion import SegmentationError, segment_expediente_documents
from .validacion import ValidationError, validate_expediente_data


class GIOJThreadingHTTPServer(ThreadingHTTPServer):
    """Servidor local exclusivo: evita dividir una selección en memoria entre procesos."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


CLIENT_CONNECTOR = """
<script>
(() => {
  const request = async (url, payload = {}) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    return response.json();
  };
  const replaceButton = (id, handler) => {
    const current = document.getElementById(id);
    const replacement = current.cloneNode(true);
    current.replaceWith(replacement);
    replacement.addEventListener('click', handler);
    return replacement;
  };
  const hint = document.querySelector('.action-hint');
  const input = document.getElementById('file-input');
  const fileList = document.getElementById('file-list');
  const summary = document.getElementById('output-summary');
  const info = document.getElementById('output-info');
  const dropzoneStatus = document.querySelector('.dropzone-status');
  let selectedExpedienteId = '';
  const show = (target, message) => { target.textContent = message; };
  const renderDocuments = (documents) => {
    fileList.textContent = '';
    for (const document of documents) {
      const item = document.createElement('li');
      item.className = 'file-item';
      item.textContent = `${document.nombre} (${document.categoria})`;
      fileList.appendChild(item);
    }
  };

  replaceButton('btn-upload', async () => {
    const result = await request('/api/proyectos/nuevo');
    show(summary, result.mensaje);
    show(info, result.detalle);
    input.removeAttribute('webkitdirectory');
    input.removeAttribute('directory');
    input.click();
  });
  input.addEventListener('change', async () => {
    const files = [...input.files];
    const documents = files.map(file => file.name);
    const firstPath = files[0]?.webkitRelativePath || '';
    const selectedDirectory = firstPath.split('/')[0];
    const expedienteId = selectedDirectory === '01_Documentos' ? '' : selectedDirectory;
    renderDocuments(documents.map(nombre => ({nombre, categoria: 'Archivo seleccionado'})));
    dropzoneStatus.textContent = `${documents.length} archivo(s) seleccionado(s). Validando expediente...`;
    try {
      const result = await request('/api/expediente/seleccion', {
        id_expediente: expedienteId,
        documentos: documents
      });
      if (result.error || !Array.isArray(result.expediente?.documentos)) {
        const message = result.error || 'La respuesta del expediente no es válida.';
        show(summary, 'No fue posible cargar el expediente.');
        show(info, message);
        hint.textContent = message;
        return;
      }
      const registeredDocuments = result.expediente.documentos;
      selectedExpedienteId = result.expediente.id;
      renderDocuments(registeredDocuments);
      dropzoneStatus.textContent = `${registeredDocuments.length} archivo(s) cargado(s) del expediente.`;
      hint.textContent = result.detalle;
    } catch (_error) {
      const message = 'No fue posible comunicarse con el lector del expediente.';
      show(summary, 'No fue posible cargar el expediente.');
      show(info, message);
      hint.textContent = message;
    }
  });
  replaceButton('btn-analyze', async () => {
    const result = await request('/api/analisis/iniciar', {id_expediente: selectedExpedienteId});
    show(summary, result.mensaje);
    show(info, result.detalle);
  });
  replaceButton('btn-generate', async () => {
    const result = await request('/api/documento/generar');
    show(summary, result.mensaje);
    show(info, result.detalle);
  });
})();
</script>
""".strip()


def _report_payload(report: StartupReport) -> dict[str, Any]:
    """Convierte el diagnóstico de arranque en una respuesta JSON segura."""
    return {
        "listo": report.is_ready,
        "diagnosticos": [
            {"estado": item.status, "asunto": item.subject, "detalle": item.detail}
            for item in report.diagnostics
        ],
    }


def _analysis_logger(log_directory: Path) -> logging.Logger:
    """Registra el detalle técnico sin exponer identificadores internos en la UI."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.web.analisis.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "analisis_web.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _visible_analysis_error(stage: str, detail: str) -> str:
    """Traduce fallos técnicos a una causa comprensible y conserva el detalle en Logs."""
    normalized = detail.casefold()
    if "estado de validación no permitido" in normalized:
        return (
            "el motor jurídico recibió estados de validación fuera del catálogo "
            "permitido"
        )
    if "no cubren exactamente 04_reglas_negocio" in normalized:
        return "las validaciones no cubrieron todas las reglas jurídicas configuradas"
    if re.search(r"\b[A-Z]{2,}(?:-[A-Z]{2,})?-\d{3}\b", detail):
        return f"{stage.casefold()} no pudo completar la evaluación de las reglas configuradas"
    return detail.rstrip(". ") or "se presentó un error sin detalle"


def create_server(project_root: Path, port: int = 0) -> ThreadingHTTPServer:
    """Crea un servidor solo local para la interfaz oficial del proyecto."""
    interface_path = project_root / "Programa" / "index.html"
    static_assets = {
        "/favicon.ico": (project_root / "Programa" / "favicon.ico", "image/x-icon"),
        "/favicon-32x32.png": (project_root / "Programa" / "favicon-32x32.png", "image/png"),
        "/favicon-16x16.png": (project_root / "Programa" / "favicon-16x16.png", "image/png"),
        "/apple-touch-icon.png": (project_root / "Programa" / "apple-touch-icon.png", "image/png"),
        "/site.webmanifest": (project_root / "Programa" / "site.webmanifest", "application/manifest+json"),
    }
    analysis_states: dict[str, dict[str, Any]] = {}
    analysis_states_lock = threading.Lock()
    selected_files: dict[str, tuple[ArchivoSeleccionado, ...]] = {}
    selected_files_lock = threading.Lock()
    analysis_logger = _analysis_logger(project_root / "Logs")
    try:
        mvp_settings = load_configuration(project_root).values.get("mvp", {})
        max_selection_mb = int(mvp_settings.get("tamano_maximo_seleccion_mb", 100)) if isinstance(mvp_settings, dict) else 100
    except (ConfigurationError, TypeError, ValueError):
        max_selection_mb = 100
    max_selection_bytes = max(1, max_selection_mb) * 1024 * 1024

    def update_analysis_state(expediente_id: str, **values: Any) -> None:
        with analysis_states_lock:
            current = analysis_states.setdefault(expediente_id, {})
            current.update(values)

    class GIOJRequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON")
            return value

        def _send_analysis_error(
            self,
            expediente_id: str,
            stage: str,
            error: Exception,
        ) -> None:
            detail = str(error).strip() or error.__class__.__name__
            visible = _visible_analysis_error(stage, detail)
            status = f"Error en {stage}: {visible}."
            analysis_logger.exception(
                "ANALISIS DETENIDO | %s | etapa=%s | %s",
                expediente_id,
                stage,
                detail,
            )
            update_analysis_state(
                expediente_id,
                estado="error",
                etapa=status,
                error={"etapa": stage, "detalle": visible},
            )
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": visible, "etapa": stage},
            )

        def _read_selected_files(self) -> tuple[ArchivoSeleccionado, ...]:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.casefold().startswith("multipart/form-data"):
                raise ValueError("La selección debe enviarse como formulario de archivos")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > max_selection_bytes:
                raise ValueError(f"La selección debe contener archivos y no superar {max_selection_mb} MB")
            body = self.rfile.read(length)
            message = BytesParser(policy=email_policy).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
            )
            files: list[ArchivoSeleccionado] = []
            names: set[str] = set()
            for part in message.iter_parts():
                if part.get_content_disposition() != "form-data" or part.get_filename() is None:
                    continue
                selected = create_selected_file(part.get_filename() or "", part.get_payload(decode=True) or b"")
                folded_name = selected.documento.nombre.casefold()
                if folded_name in names:
                    raise ValueError(f"No seleccione dos archivos con el mismo nombre: {selected.documento.nombre}")
                if not selected.contenido:
                    raise ValueError(f"El archivo {selected.documento.nombre} está vacío")
                names.add(folded_name)
                files.append(selected)
            if not files:
                raise ValueError("Seleccione al menos un archivo compatible")
            return tuple(files)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            asset = static_assets.get(parsed.path)
            if asset is not None:
                asset_path, content_type = asset
                if not asset_path.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Recurso estático no encontrado"})
                    return
                body = asset_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/":
                if not interface_path.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Interfaz no encontrada"})
                    return
                body = interface_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/estado":
                payload = _report_payload(initialize_project(project_root))
                payload["limites"] = {"tamano_maximo_seleccion_mb": max_selection_mb}
                self._send_json(HTTPStatus.OK, payload)
                return
            if parsed.path == "/api/expedientes":
                try:
                    expedientes = list_expedientes(project_root)
                except ExpedienteError as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {
                    "expedientes": [
                        {"id": item.id_expediente, "documentos": len(item.documentos)}
                        for item in expedientes
                    ],
                })
                return
            if parsed.path == "/api/analisis/progreso":
                expediente_id = parse_qs(parsed.query).get("id_expediente", [""])[0]
                with analysis_states_lock:
                    state = dict(analysis_states.get(expediente_id, {"estado": "sin_iniciar"}))
                self._send_json(HTTPStatus.OK, state)
                return
            if parsed.path == "/api/revision/analista":
                expediente_id = parse_qs(parsed.query).get("id_expediente", [""])[0]
                try:
                    review = load_analyst_review(project_root, expediente_id)
                except AnalystReviewError as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {"revision_analista": asdict(review)})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/servidor/detener":
                self._send_json(HTTPStatus.OK, {"mensaje": "Servidor GIOJ detenido."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == "/api/archivos/seleccion":
                try:
                    files = self._read_selected_files()
                except (ExpedienteError, TypeError, ValueError) as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                selection_id = f"SEL-{uuid4().hex[:12].upper()}"
                with selected_files_lock:
                    selected_files.clear()
                    selected_files[selection_id] = files
                self._send_json(HTTPStatus.OK, {
                    "mensaje": "Archivos seleccionados.",
                    "detalle": (
                        f"{len(files)} archivo(s) disponibles solo en memoria. "
                        "Los originales no fueron copiados ni modificados."
                    ),
                    "seleccion": {
                        "id": selection_id,
                        "documentos": [
                            {
                                "nombre": item.documento.nombre,
                                "categoria": item.documento.categoria,
                            }
                            for item in files
                        ],
                    },
                })
                return
            try:
                payload = self._read_json()
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Solicitud JSON inválida"})
                return
            if self.path == "/api/proyectos/nuevo":
                report = initialize_project(project_root)
                status = HTTPStatus.OK if report.is_ready else HTTPStatus.SERVICE_UNAVAILABLE
                self._send_json(status, {
                    **_report_payload(report),
                    "mensaje": "Proyecto inicializado." if report.is_ready else "El proyecto no está listo.",
                    "detalle": "Use Seleccionar archivos para preparar los documentos del análisis.",
                })
                return
            if self.path == "/api/expediente/seleccion":
                expediente_id = payload.get("id_expediente")
                try:
                    if not isinstance(expediente_id, str) or not expediente_id.strip():
                        raise ExpedienteError("Seleccione un expediente disponible creado en Expedientes antes de analizar.")
                    expediente = read_expediente(project_root, expediente_id)
                except ExpedienteError as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {
                    "mensaje": "Expediente cargado.",
                    "detalle": f"{len(expediente.documentos)} archivo(s) registrado(s). El contenido no ha sido procesado.",
                    "expediente": {
                        "id": expediente.id_expediente,
                        "ubicacion_original": expediente.ubicacion_original,
                        "documentos": [
                            {
                                "nombre": item.nombre,
                                "ubicacion_original": item.ubicacion_original,
                                "categoria": item.categoria,
                            }
                            for item in expediente.documentos
                        ],
                    },
                })
                return
            if self.path == "/api/analisis/iniciar":
                expediente_id = payload.get("id_expediente")
                if not isinstance(expediente_id, str) or not expediente_id.strip():
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Seleccione los archivos antes de analizar."})
                    return
                with selected_files_lock:
                    memory_files = selected_files.get(expediente_id)
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Preparando el expediente",
                    documento=None,
                    pagina=None,
                )

                def report_progress(
                    documento: str,
                    pagina: int | None,
                    completadas: int,
                    total: int,
                    etapa: str,
                ) -> None:
                    update_analysis_state(
                        expediente_id,
                        estado="procesando",
                        etapa=etapa,
                        documento=documento or None,
                        pagina=pagina,
                        completadas=completadas,
                        total=total,
                    )

                try:
                    result = (
                        extract_selected_files_text(project_root, expediente_id, memory_files, report_progress)
                        if memory_files is not None
                        else extract_expediente_text(project_root, expediente_id, report_progress)
                    )
                except OCRExtractionError as error:
                    self._send_analysis_error(expediente_id, "extracción OCR", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Segmentando documentos lógicos",
                    documento=None,
                    pagina=None,
                )
                try:
                    segmentation = segment_expediente_documents(
                        project_root, expediente_id, result.textos
                    )
                except SegmentationError as error:
                    self._send_analysis_error(expediente_id, "segmentación documental", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Clasificando documentos",
                    documento=None,
                    pagina=None,
                )
                try:
                    classification = classify_expediente_documents(
                        project_root,
                        expediente_id,
                        tuple(item.documento for item in memory_files) if memory_files is not None else None,
                    )
                except ClassificationError as error:
                    self._send_analysis_error(expediente_id, "clasificación documental", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Extrayendo campos jurídicos",
                    documento=None,
                    pagina=None,
                )
                try:
                    extraction = extract_expediente_data(project_root, expediente_id)
                except ExtractionError as error:
                    self._send_analysis_error(expediente_id, "extracción de datos", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Normalizando datos extraídos",
                    documento=None,
                    pagina=None,
                )
                try:
                    normalization = normalize_expediente_data(project_root, expediente_id)
                except NormalizationError as error:
                    self._send_analysis_error(expediente_id, "normalización documental", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Aplicando validaciones documentales",
                    documento=None,
                    pagina=None,
                )
                try:
                    validation = validate_expediente_data(project_root, expediente_id)
                except ValidationError as error:
                    self._send_analysis_error(expediente_id, "validaciones documentales", error)
                    return
                update_analysis_state(
                    expediente_id,
                    estado="procesando",
                    etapa="Aplicando motor jurídico",
                    documento=None,
                    pagina=None,
                )
                try:
                    legal_result = apply_legal_engine(project_root, expediente_id)
                except LegalEngineError as error:
                    self._send_analysis_error(expediente_id, "motor jurídico", error)
                    return
                try:
                    analyst_review = initialize_analyst_review(
                        project_root, expediente_id, legal_result.resultado
                    )
                except AnalystReviewError as error:
                    self._send_analysis_error(
                        expediente_id, "preparación de la revisión del analista", error
                    )
                    return
                update_analysis_state(
                    expediente_id,
                    estado="completado",
                    etapa="Análisis y motor jurídico completados",
                    documento=None,
                    pagina=None,
                    archivo_salida=result.archivo_salida,
                    archivo_segmentacion=segmentation.archivo_salida,
                    archivo_clasificacion=classification.archivo_salida,
                    archivo_extraccion=extraction.archivo_salida,
                    archivo_normalizacion=normalization.archivo_salida,
                    archivo_validaciones=validation.archivo_salida,
                    archivo_resultado_juridico=legal_result.archivo_salida,
                    resultado_preliminar=legal_result.resultado,
                    estado_revision_analista=analyst_review.estado,
                    errores=len(result.errores),
                )
                self._send_json(HTTPStatus.OK, {
                    "mensaje": f"Resultado jurídico preliminar: {legal_result.resultado}.",
                    "detalle": (
                        f"{len(result.textos)} página(s) procesada(s), {len(result.errores)} error(es). "
                        f"Clasificación: {classification.archivo_salida}. "
                        f"Extracción: {extraction.archivo_salida}. "
                        f"Normalización: {normalization.archivo_salida}. "
                        f"Validaciones: {validation.archivo_salida}. "
                        f"Motor jurídico: {legal_result.archivo_salida}"
                    ),
                    "ocr": {
                        "archivo_salida": result.archivo_salida,
                        "errores": [
                            {"documento": item.documento, "pagina": item.pagina, "detalle": item.detalle}
                            for item in result.errores
                        ],
                    },
                    "clasificacion": {
                        "archivo_salida": classification.archivo_salida,
                        "documentos": [
                            {
                                "documento": item.documento,
                                "tipo_documental": item.tipo_documental,
                                "codigo_tipo_documental": item.codigo_tipo_documental,
                                "estado": item.estado,
                                "observacion": item.observacion,
                            }
                            for item in classification.documentos
                        ],
                    },
                    "extraccion": {
                        "archivo_salida": extraction.archivo_salida,
                        "campos": len(extraction.campos),
                        "resumen": asdict(extraction.resumen) if extraction.resumen else None,
                        "advertencias_configuracion": list(extraction.advertencias_configuracion),
                    },
                    "normalizacion": {
                        "archivo_salida": normalization.archivo_salida,
                        "normalizaciones": len(normalization.normalizaciones),
                        "resumen": asdict(normalization.resumen),
                        "advertencias_configuracion": list(normalization.advertencias_configuracion),
                    },
                    "validacion": {
                        "archivo_salida": validation.archivo_salida,
                        "resumen": asdict(validation.resumen),
                        "reglas": [asdict(item) for item in validation.validaciones],
                    },
                    "motor_juridico": {
                        "archivo_salida": legal_result.archivo_salida,
                        "resultado": legal_result.resultado,
                        "resultado_preliminar": legal_result.resultado,
                        "concepto_juridico": legal_result.concepto_juridico,
                        "resumen": asdict(legal_result.resumen),
                        "observaciones": [asdict(item) for item in legal_result.observaciones],
                    },
                    "segmentacion": {
                        "archivo_salida": segmentation.archivo_salida,
                        "documentos_logicos": [
                            asdict(item) for item in segmentation.documentos_logicos
                        ],
                    },
                    "trazabilidad": (
                        asdict(legal_result.trazabilidad)
                        if legal_result.trazabilidad is not None
                        else None
                    ),
                    "revision_analista": asdict(analyst_review),
                })
                return
            if self.path == "/api/revision/analista":
                expediente_id = payload.get("id_expediente")
                decision = payload.get("decision")
                observation = payload.get("observacion", "")
                validation_reviews = payload.get("validaciones")
                if not all(isinstance(item, str) for item in (expediente_id, decision, observation)):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "La revisión contiene datos inválidos"})
                    return
                try:
                    review = record_analyst_review(
                        project_root,
                        expediente_id,
                        decision,
                        observation,
                        validation_reviews if isinstance(validation_reviews, list) else None,
                    )
                except AnalystReviewError as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {
                    "mensaje": f"Análisis {review.estado.lower()} por el analista.",
                    "revision_analista": asdict(review),
                })
                return
            if self.path == "/api/documento/generar":
                expediente_id = payload.get("id_expediente")
                if not isinstance(expediente_id, str):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "El expediente es obligatorio"})
                    return
                try:
                    generated = generate_official_document(project_root, expediente_id)
                except DocumentGenerationError as error:
                    self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {
                    "mensaje": "Documento oficial generado.",
                    "detalle": (
                        f"Word: {generated.archivo_word}. PDF: {generated.archivo_pdf}. "
                        "El consecutivo permanece reservado para diligenciamiento manual del analista."
                    ),
                    "generacion": asdict(generated),
                })
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})

        def log_message(self, _format: str, *_args: object) -> None:
            """Evita registrar datos del navegador fuera de los logs de GIOJ."""

    return GIOJThreadingHTTPServer(("127.0.0.1", port), GIOJRequestHandler)


def _existing_gioj_url(port: int) -> str | None:
    """Reconoce una instancia GIOJ ya activa para que el arranque sea idempotente."""
    if port <= 0:
        return None
    base_url = f"http://127.0.0.1:{port}/"
    try:
        with urlopen(f"{base_url}api/estado", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("listo"), bool) or not isinstance(payload.get("diagnosticos"), list):
        return None
    return base_url


def stop_interface(port: int = 8000) -> int:
    """Detiene de forma limpia una instancia local de GIOJ desde otra terminal."""
    existing_url = _existing_gioj_url(port)
    if not existing_url:
        print(f"No hay una instancia disponible de GIOJ en http://127.0.0.1:{port}/")
        return 1
    request = Request(f"{existing_url}api/servidor/detener", data=b"", method="POST")
    try:
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        print(f"No fue posible detener GIOJ en {existing_url}")
        return 1
    print(str(payload.get("mensaje", "Servidor GIOJ detenido.")))
    return 0


def serve_interface(project_root: Path, port: int = 0) -> int:
    """Inicia la interfaz local cuando la configuración del proyecto es válida."""
    existing_url = _existing_gioj_url(port)
    if existing_url:
        print(
            f"GIOJ ya está activo en {existing_url} "
            "No es necesario iniciar otra instancia; recargue esa página para continuar."
        )
        return 0
    report = initialize_project(project_root)
    if not report.is_ready:
        print(report.to_console())
        return 1
    try:
        server = create_server(project_root, port)
    except OSError:
        existing_url_after_bind = _existing_gioj_url(port)
        if existing_url_after_bind:
            print(
                f"GIOJ ya está activo en {existing_url_after_bind} "
                "No es necesario iniciar otra instancia; recargue esa página para continuar."
            )
            return 0
        print(
            f"No fue posible iniciar GIOJ en el puerto {port}: "
            "otro programa está usando ese puerto y no corresponde a una instancia disponible de GIOJ."
        )
        return 1
    address, selected_port = server.server_address[:2]
    print(f"Interfaz GIOJ disponible en http://{address}:{selected_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor GIOJ detenido.")
    finally:
        server.server_close()
    return 0
