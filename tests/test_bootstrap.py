"""Pruebas de la inicialización GIOJ-001."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from urllib.request import Request, urlopen
from pathlib import Path

from Codigo.bootstrap import initialize_project
from Codigo.config import ConfigurationError, resolve_project_path
from Codigo.web import create_server


SHEETS = {
    "campos": "01_Campos_Extraccion",
    "matriz": "02_Matriz_Origen_Datos",
    "catalogos": "03_Catalogos",
    "reglas": "04_Reglas_Negocio",
    "extraccion": "05_Extraccion_Documental",
    "flujo": "06_Flujo_Analisis_Conformidad",
    "salida": "07_Salida_Analisis",
    "trazabilidad": "08_Trazabilidad",
    "marcadores": "09_Marcadores_Documento",
    "formateadores": "10_Formateadores",
}


def write_workbook(path: Path, sheets: list[str]) -> None:
    """Crea un XLSX mínimo válido solo para validar la lectura de hojas."""
    nodes = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheets, start=1)
    )
    xml = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{nodes}</sheets></workbook>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", xml)


class BootstrapTests(unittest.TestCase):
    def create_project(self, *, include_templates: bool = True, sheets: list[str] | None = None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "Arquitectura").mkdir()
        config = {
            "rutas": {
                "arquitectura": "./Arquitectura/Arquitectura.xlsx", "plantillas": "./Plantillas/",
                "expedientes": "./Expedientes/", "conocimiento": "./Conocimiento/",
                "salida": "./Salida/", "logs": "./Logs/", "codigo": "./Codigo/",
            },
            "archivos": {
                "plantilla_conformidad": "Certificado_Conformidad.docx",
                "plantilla_no_conformidad": "Certificado_No_Conformidad.docx", "readme": "./README.md",
            },
            "hojas": SHEETS,
        }
        (root / "Arquitectura" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "README.md").write_text("Prueba", encoding="utf-8")
        write_workbook(root / "Arquitectura" / "Arquitectura.xlsx", sheets or list(SHEETS.values()))
        if include_templates:
            templates = root / "Plantillas"
            templates.mkdir()
            for name in ("Certificado_Conformidad.docx", "Certificado_No_Conformidad.docx"):
                (templates / name).write_bytes(b"plantilla")
        return root

    def test_initialization_is_ready_and_creates_runtime_structure(self) -> None:
        root = self.create_project()
        report = initialize_project(root)
        self.assertTrue(report.is_ready)
        self.assertTrue((root / "Logs" / "inicializacion.log").is_file())
        self.assertTrue((root / "Expedientes" / "Pruebas" / "02_Trabajo").is_dir())

    def test_missing_template_is_reported_without_creating_it(self) -> None:
        root = self.create_project(include_templates=False)
        report = initialize_project(root)
        self.assertFalse(report.is_ready)
        self.assertIn("Plantilla Certificado_Conformidad.docx", report.to_console())
        self.assertFalse((root / "Plantillas" / "Certificado_Conformidad.docx").exists())

    def test_missing_architecture_sheet_is_reported(self) -> None:
        root = self.create_project(sheets=list(SHEETS.values())[:-1])
        report = initialize_project(root)
        self.assertFalse(report.is_ready)
        self.assertIn("Hoja 10_Formateadores", report.to_console())

    def test_absolute_configuration_path_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            resolve_project_path(Path.cwd(), "C:/ruta/no_permitida")

    def test_interface_is_served_without_modifying_the_source_file(self) -> None:
        root = self.create_project()
        source = (root / "Programa")
        source.mkdir()
        interface = source / "index.html"
        original = "<html><body><button id='btn-upload'></button></body></html>"
        interface.write_text(original, encoding="utf-8")
        server = create_server(root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address, port = server.server_address[:2]
            with urlopen(f"http://{address}:{port}/") as response:
                delivered = response.read().decode("utf-8")
            self.assertIn("/api/proyectos/nuevo", delivered)
            self.assertEqual(interface.read_text(encoding="utf-8"), original)
        finally:
            server.shutdown()
            server.server_close()

    def test_new_project_endpoint_returns_readiness(self) -> None:
        root = self.create_project()
        server = create_server(root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address, port = server.server_address[:2]
            request = Request(
                f"http://{address}:{port}/api/proyectos/nuevo",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["listo"])
            self.assertEqual(payload["mensaje"], "Proyecto inicializado.")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
