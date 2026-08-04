"""Pruebas de la lectura de expedientes GIOJ-003."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from Codigo.expediente import ExpedienteError, read_expediente
from Codigo.web import create_server


def create_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    configuration = {"rutas": {"expedientes": "./Expedientes/", "logs": "./Logs/"}}
    (root / "Arquitectura" / "config.json").write_text(json.dumps(configuration), encoding="utf-8")
    return root


class ExpedienteTests(unittest.TestCase):
    def test_read_expediente_registers_every_file_without_reading_contents(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-001" / "01_Documentos"
        nested = documents / "Anexos"
        nested.mkdir(parents=True)
        (documents / "escritura.PDF").write_text("contenido que no debe procesarse", encoding="utf-8")
        (documents / "minuta.docx").write_bytes(b"documento")
        (nested / "imagen.JpG").write_bytes(b"imagen")
        (nested / "soporte.txt").write_text("soporte", encoding="utf-8")

        expediente = read_expediente(root, "EXP-001")

        self.assertEqual(expediente.id_expediente, "EXP-001")
        self.assertEqual(expediente.ubicacion_original, "Expedientes/EXP-001")
        self.assertEqual(
            [(item.nombre, item.categoria) for item in expediente.documentos],
            [("imagen.JpG", "Imagen"), ("soporte.txt", "Otro documento"), ("escritura.PDF", "PDF"), ("minuta.docx", "Documento Word")],
        )
        self.assertEqual(
            {item.ubicacion_original for item in expediente.documentos},
            {
                "Expedientes/EXP-001/01_Documentos/escritura.PDF",
                "Expedientes/EXP-001/01_Documentos/minuta.docx",
                "Expedientes/EXP-001/01_Documentos/Anexos/imagen.JpG",
                "Expedientes/EXP-001/01_Documentos/Anexos/soporte.txt",
            },
        )
        log = (root / "Logs" / "expediente.log").read_text(encoding="utf-8")
        self.assertIn("ARCHIVO ENCONTRADO | PDF | Expedientes/EXP-001/01_Documentos/escritura.PDF", log)
        self.assertIn("ARCHIVO ENCONTRADO | Imagen | Expedientes/EXP-001/01_Documentos/Anexos/imagen.JpG", log)

    def test_read_expediente_rejects_paths_outside_expedientes(self) -> None:
        root = create_project()
        with self.assertRaisesRegex(ExpedienteError, "identificador"):
            read_expediente(root, "../fuera")

    def test_read_expediente_requires_documents_directory(self) -> None:
        root = create_project()
        (root / "Expedientes" / "EXP-002").mkdir(parents=True)
        with self.assertRaisesRegex(ExpedienteError, "01_Documentos"):
            read_expediente(root, "EXP-002")

    def test_selection_endpoint_reads_only_the_selected_expediente(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-003" / "01_Documentos"
        documents.mkdir(parents=True)
        (documents / "ctl.pdf").write_bytes(b"sin procesar")
        server = create_server(root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address, port = server.server_address[:2]
            request = Request(
                f"http://{address}:{port}/api/expediente/seleccion",
                data=json.dumps({"id_expediente": "EXP-003"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["mensaje"], "Expediente cargado.")
            self.assertEqual(payload["expediente"]["documentos"], [{
                "nombre": "ctl.pdf",
                "ubicacion_original": "Expedientes/EXP-003/01_Documentos/ctl.pdf",
                "categoria": "PDF",
            }])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
