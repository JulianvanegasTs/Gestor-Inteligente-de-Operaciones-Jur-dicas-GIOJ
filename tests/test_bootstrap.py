"""Pruebas de la inicialización GIOJ-001."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from Codigo.bootstrap import initialize_project
from Codigo.config import ConfigurationError, resolve_project_path


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


if __name__ == "__main__":
    unittest.main()
