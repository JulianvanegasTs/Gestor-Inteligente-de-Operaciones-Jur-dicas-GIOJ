"""Pruebas de la clasificación documental GIOJ-005."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.clasificacion import classify_expediente_documents


def _sheet_xml(rows: list[list[str]]) -> str:
    body: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row, start=1):
            letter = chr(ord("A") + column - 1)
            if value in {"0", "1"}:
                cells.append(f'<c r="{letter}{row_number}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{letter}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def _write_architecture(root: Path) -> None:
    sheets = {
        "01_Campos_Extraccion": [
            ["ID_Campo", "Catalogo_Asociado"],
            ["PER-003", "Tipo_Documento"],
        ],
        "02_Matriz_Origen_Datos": [
            ["ID_Campo", "Entidad", "Campo", "Documento_Identidad"],
            ["PER-003", "Persona", "Tipo_Documento", "1"],
        ],
        "03_Catalogos": [
            ["Catalogo", "Codigo", "Valor", "Activo"],
            ["Tipo_Documento_Expediente", "DOC_ID", "Documento de Identidad", "1"],
            ["Tipo_Documento", "TD_CC", "Cédula de ciudadanía", "1"],
        ],
        "05_Extraccion_Documental": [
            ["ID_Extraccion", "ID_Campo", "Documento_Origen"],
            ["EXT-007", "PER-003", "Documento_Identidad"],
        ],
    }
    architecture = root / "Arquitectura" / "Arquitectura.xlsx"
    namespaces = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(architecture, "w") as workbook:
        content_types = (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{number}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for number in range(1, len(sheets) + 1)
            )
            + "</Types>"
        )
        workbook.writestr("[Content_Types].xml", content_types)
        workbook.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{namespaces}"><sheets>'
            + "".join(f'<sheet name="{name}" sheetId="{number}" r:id="rId{number}"/>' for number, name in enumerate(sheets, start=1))
            + "</sheets></workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{number}.xml"/>'
                for number in range(1, len(sheets) + 1)
            )
            + "</Relationships>",
        )
        for number, rows in enumerate(sheets.values(), start=1):
            workbook.writestr(f"xl/worksheets/sheet{number}.xml", _sheet_xml(rows))


def create_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    configuration = {
        "rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "expedientes": "./Expedientes/", "logs": "./Logs/", "salida": "./Salida/"},
        "hojas": {"campos": "01_Campos_Extraccion", "matriz": "02_Matriz_Origen_Datos", "catalogos": "03_Catalogos", "extraccion": "05_Extraccion_Documental"},
        "ocr": {"archivo_salida": "texto_extraido.json"},
    }
    (root / "Arquitectura" / "config.json").write_text(json.dumps(configuration), encoding="utf-8")
    _write_architecture(root)
    return root


class ClassificationTests(unittest.TestCase):
    def test_classifies_from_catalog_and_extraction_definition(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-001" / "01_Documentos"
        documents.mkdir(parents=True)
        identity = documents / "soporte.pdf"
        unknown = documents / "anexo.pdf"
        identity.write_bytes(b"origen sin modificar")
        unknown.write_bytes(b"origen sin modificar")
        output = root / "Salida" / "EXP-001"
        output.mkdir(parents=True)
        (output / "texto_extraido.json").write_text(
            json.dumps(
                {
                    "id_expediente": "EXP-001",
                    "textos": [
                        {
                            "documento": "Expedientes/EXP-001/01_Documentos/soporte.pdf",
                            "pagina": 1,
                            "texto": "REPUBLICA DE COLOMBIA CEDULA DE CIUDADANIA",
                        },
                        {
                            "documento": "Expedientes/EXP-001/01_Documentos/anexo.pdf",
                            "pagina": 1,
                            "texto": "contenido sin evidencia documental configurada",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = classify_expediente_documents(root, "EXP-001")

        self.assertEqual(result.archivo_salida, "Salida/EXP-001/clasificacion_documental.json")
        classified = {Path(item.documento).name: item for item in result.documentos}
        self.assertEqual(classified["soporte.pdf"].tipo_documental, "Documento de Identidad")
        self.assertEqual(classified["soporte.pdf"].codigo_tipo_documental, "DOC_ID")
        self.assertEqual(classified["soporte.pdf"].evidencias[0].pagina, 1)
        self.assertEqual(classified["anexo.pdf"].estado, "No identificado")
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        saved_documents = {Path(item["documento"]).name: item for item in saved["documentos"]}
        self.assertEqual(saved_documents["soporte.pdf"]["tipo_documental"], "Documento de Identidad")
        self.assertIsNone(saved_documents["anexo.pdf"]["tipo_documental"])
        self.assertEqual(identity.read_bytes(), b"origen sin modificar")
        self.assertEqual(unknown.read_bytes(), b"origen sin modificar")
        self.assertIn("CLASIFICACION COMPLETADA", (root / "Logs" / "clasificacion.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
