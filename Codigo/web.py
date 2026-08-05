"""Servidor local que conecta la interfaz oficial con el motor de GIOJ."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .bootstrap import StartupReport, initialize_project
from .expediente import ExpedienteError, find_expediente_id, read_expediente
from .ocr import OCRExtractionError, extract_expediente_text


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


def create_server(project_root: Path, port: int = 0) -> ThreadingHTTPServer:
    """Crea un servidor solo local para la interfaz oficial del proyecto."""
    interface_path = project_root / "Programa" / "index.html"

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

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
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
            if self.path == "/api/estado":
                self._send_json(HTTPStatus.OK, _report_payload(initialize_project(project_root)))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})

        def do_POST(self) -> None:  # noqa: N802
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
                    "detalle": "Seleccione los documentos del expediente para continuar.",
                })
                return
            if self.path == "/api/expediente/seleccion":
                expediente_id = payload.get("id_expediente")
                try:
                    if not isinstance(expediente_id, str) or not expediente_id.strip():
                        expediente_id = find_expediente_id(project_root, payload.get("documentos", []))
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
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Seleccione un expediente antes de analizar."})
                    return
                try:
                    result = extract_expediente_text(project_root, expediente_id)
                except OCRExtractionError as error:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.OK, {
                    "mensaje": "Texto documental extraído.",
                    "detalle": (
                        f"{len(result.textos)} página(s) procesada(s), {len(result.errores)} error(es). "
                        f"Resultado: {result.archivo_salida}"
                    ),
                    "ocr": {
                        "archivo_salida": result.archivo_salida,
                        "errores": [
                            {"documento": item.documento, "pagina": item.pagina, "detalle": item.detalle}
                            for item in result.errores
                        ],
                    },
                })
                return
            pending = {
                "/api/documento/generar": ("Generación pendiente.", "La generación documental se implementará en GIOJ-012 y GIOJ-013."),
            }
            if self.path in pending:
                message, detail = pending[self.path]
                self._send_json(HTTPStatus.CONFLICT, {"mensaje": message, "detalle": detail})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})

        def log_message(self, _format: str, *_args: object) -> None:
            """Evita registrar datos del navegador fuera de los logs de GIOJ."""

    return ThreadingHTTPServer(("127.0.0.1", port), GIOJRequestHandler)


def serve_interface(project_root: Path, port: int = 0) -> int:
    """Inicia la interfaz local cuando la configuración del proyecto es válida."""
    report = initialize_project(project_root)
    if not report.is_ready:
        print(report.to_console())
        return 1
    server = create_server(project_root, port)
    address, selected_port = server.server_address[:2]
    print(f"Interfaz GIOJ disponible en http://{address}:{selected_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor GIOJ detenido.")
    finally:
        server.server_close()
    return 0
