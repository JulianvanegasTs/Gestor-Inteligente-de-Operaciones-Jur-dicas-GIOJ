"""Pruebas del motor de extracción documental GIOJ-006."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.extraccion import extract_expediente_data


def _sheet_xml(rows: list[list[str]]) -> str:
    body: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells = [
            f'<c r="{chr(ord("A") + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        ]
        body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>')


def _write_architecture(root: Path) -> None:
    sheets = {
        "01_Campos_Extraccion": [
            ["ID_Campo", "Nivel", "Campo_Padre", "Entidad", "Campo", "Descripción", "Tipo_Dato", "Catalogo_Asociado", "Múltiples", "Obligatorio", "Observaciones", "Mostrar_Resultado"],
            ["PER-001", "Entidad", "", "Persona", "Intervinientes", "Personas", "Lista_Objeto", "", "Sí", "Sí", "", ""],
            ["PER-002", "Atributo", "Intervinientes", "Persona", "Nombre", "Nombre completo", "Texto", "", "No", "Sí", "", "Si"],
            ["ESC-004", "Atributo", "Escrituras", "Escritura", "Fecha", "Fecha", "Fecha", "", "No", "Sí", "", "Si"],
        ],
        "05_Extraccion_Documental": [
            ["ID_Extraccion", "ID_Campo", "Prioridad", "Documento_Origen", "Regla_Extraccion", "Regla_Validacion", "Permite_OCR", "Puede_Heredarse", "Campo_Destino", "Observaciones"],
            ["EXT-001", "PER-002", "1", "Documento_Identidad", "Extraer nombre completo.", "", "Sí", "No", "Intervinientes[].Nombre", ""],
            ["EXT-002", "ESC-004", "1", "Escritura_Firma", "Extraer fecha de escritura.", "", "Sí", "No", "Escrituras[].Fecha", ""],
            ["EXT-003", "INEXISTENTE-001", "1", "Documento_Identidad", "No crear campos.", "", "Sí", "No", "", ""],
        ],
    }
    architecture = root / "Arquitectura" / "Arquitectura.xlsx"
    relationship_namespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(architecture, "w") as workbook:
        workbook.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{number}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for number in range(1, len(sheets) + 1)) + "</Types>")
        workbook.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
        workbook.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{relationship_namespace}"><sheets>'
            + "".join(f'<sheet name="{name}" sheetId="{number}" r:id="rId{number}"/>' for number, name in enumerate(sheets, start=1)) + "</sheets></workbook>")
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{number}.xml"/>' for number in range(1, len(sheets) + 1)) + "</Relationships>")
        for number, rows in enumerate(sheets.values(), start=1):
            workbook.writestr(f"xl/worksheets/sheet{number}.xml", _sheet_xml(rows))


def create_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    (root / "Arquitectura" / "config.json").write_text(json.dumps({
        "rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "logs": "./Logs/", "salida": "./Salida/"},
        "hojas": {"campos": "01_Campos_Extraccion", "extraccion": "05_Extraccion_Documental"},
        "ocr": {"archivo_salida": "texto_extraido.json"},
        "extraccion": {"archivo_salida": "campos.json"},
    }), encoding="utf-8")
    _write_architecture(root)
    return root


class ExtractionTests(unittest.TestCase):
    def test_extracts_only_configured_fields_and_keeps_page_evidence(self) -> None:
        root = create_project()
        output = root / "Salida" / "EXP-001"
        output.mkdir(parents=True)
        document = "Expedientes/EXP-001/01_Documentos/cedula.pdf"
        (output / "texto_extraido.json").write_text(json.dumps({"id_expediente": "EXP-001", "textos": [
            {"documento": document, "pagina": 2, "texto": "Nombre: ANA PEREZ", "metodo": "OCR", "confianza": 92.5},
        ]}, ensure_ascii=False), encoding="utf-8")
        (output / "clasificacion_documental.json").write_text(json.dumps({"id_expediente": "EXP-001", "documentos": [
            {"documento": document, "tipo_documental": "Documento de Identidad", "codigo_tipo_documental": "DOC_ID"},
        ]}, ensure_ascii=False), encoding="utf-8")

        result = extract_expediente_data(root, "EXP-001")

        self.assertEqual(result.archivo_salida, "Salida/EXP-001/campos.json")
        self.assertEqual([item.campo.id_campo for item in result.campos], ["PER-001", "PER-002", "ESC-004"])
        nombre = next(item for item in result.campos if item.campo.id_campo == "PER-002")
        self.assertEqual(nombre.estado, "Extraído")
        self.assertEqual(nombre.valores[0].valor_encontrado, "ANA PEREZ")
        self.assertEqual(nombre.valores[0].pagina, 2)
        self.assertEqual(nombre.valores[0].documento, document)
        self.assertEqual(nombre.valores[0].confianza, 92.5)
        self.assertEqual(len(result.advertencias_configuracion), 1)
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["campos"]), 3)
        self.assertIn("INEXISTENTE-001", saved["advertencias_configuracion"][0])
        self.assertIn("EXTRACCION COMPLETADA", (root / "Logs" / "extraccion.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
