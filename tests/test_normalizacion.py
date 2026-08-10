"""Pruebas de normalización GIOJ-007."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.normalizacion import normalize_expediente_data


ROWS = [
    ["ID_Formateador", "Nombre_Formateador", "Tipo_Entrada", "Campos_Entrada", "Formato_Salida", "Regla_Formateo"],
    ["FOR-001", "Largo_Español", "Fecha", "Fecha", "Texto Jurídico", "Convertir la fecha al formato jurídico largo en español."],
    ["FOR-002", "Formato_Moneda", "Moneda", "CRE-004", "Moneda", "Mostrar separador de miles y símbolo $."],
    ["FOR-003", "Nombre_Completo", "Texto", "PER-002", "Texto", "Eliminar espacios dobles y conservar mayúsculas originales."],
    ["FOR-004", "Lista_Matriculas", "Lista", "INM-003", "Lista", "Unir todas las matrículas separadas por coma."],
    ["FOR-008", "Notaria_Texto", "Número", "Notaria", "Texto Jurídico", "Convertir el número de notaría al formato utilizado en documentos jurídicos."],
    ["FOR-010", "Estado_Civil", "Texto", "PER-Estado_Civil", "Texto Jurídico", "Convertir el estado civil al texto jurídico correspondiente."],
    ["FOR-011", "Documento_Identidad", "Objeto", "PER-003,PER-004", "Texto", "Construir el documento completo."],
    ["FOR-012", "Referencia_Credito", "Objeto", "CRE-002,CRE-003", "Texto", "Construir la descripción completa del crédito."],
]


def _workbook(path: Path) -> None:
    body = []
    for number, row in enumerate(ROWS, 1):
        cells = "".join(f'<c r="{chr(65 + index)}{number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>' for index, value in enumerate(row))
        body.append(f'<row r="{number}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="10_Formateadores" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        book.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(body) + "</sheetData></worksheet>")


def _field(field_id: str, name: str, kind: str, *values: str) -> dict[str, object]:
    return {"id_campo": field_id, "campo": name, "tipo_dato": kind, "valores": [{"valor_encontrado": value, "documento": "fuente.pdf", "pagina": 2} for value in values]}


class NormalizationTests(unittest.TestCase):
    def test_uses_architecture_and_preserves_value_and_evidence(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "Arquitectura").mkdir()
        (root / "Salida" / "EXP-007").mkdir(parents=True)
        _workbook(root / "Arquitectura" / "Arquitectura.xlsx")
        (root / "Arquitectura" / "config.json").write_text(json.dumps({"rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "salida": "./Salida/", "logs": "./Logs/"}, "hojas": {"formateadores": "10_Formateadores"}, "extraccion": {"archivo_salida": "extraccion_documental.json"}, "normalizacion": {"archivo_salida": "normalizacion_documental.json"}}), encoding="utf-8")
        fields = [
            _field("ESC-004", "Fecha", "Fecha", "2026-06-09"), _field("CRE-004", "Monto_Prestamo", "Moneda", "2.5E8"),
            _field("PER-002", "Nombre", "Texto", "JUAN  PÉREZ GÓMEZ"), _field("INM-003", "Matricula", "Texto", "50N-123", "50N-456"),
            _field("ESC-005", "Notaria", "Texto", "1"), _field("PER-Estado_Civil", "Estado_Civil", "Texto", "CASADO"),
            {"id_campo": "PER-001", "objetos": [{"campos": [{"id_campo": "PER-003", "valores": ["CC"], "evidencias": [{"documento": "fuente.pdf", "pagina": 2}]}, {"id_campo": "PER-004", "valores": ["123456789"], "evidencias": [{"documento": "fuente.pdf", "pagina": 2}]}]}]},
            {"id_campo": "CRE-001", "objetos": [{"campos": [{"id_campo": "CRE-002", "valores": ["CAVIPETROL"], "evidencias": []}, {"id_campo": "CRE-003", "valores": ["Vivienda"], "evidencias": []}]}]},
        ]
        source = root / "Salida" / "EXP-007" / "extraccion_documental.json"
        source.write_text(json.dumps({"id_expediente": "EXP-007", "campos": fields}, ensure_ascii=False), encoding="utf-8")

        result = normalize_expediente_data(root, "EXP-007")

        self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["campos"], fields)
        values = {item.id_formateador: item.valor_normalizado for item in result.normalizaciones}
        self.assertEqual(values, {"FOR-001": "9 de junio de 2026", "FOR-002": "$250.000.000", "FOR-003": "JUAN PÉREZ GÓMEZ", "FOR-004": "50N-123, 50N-456", "FOR-008": "Primera (1a)", "FOR-010": "Casado(a)", "FOR-011": "CC No. 123456789", "FOR-012": "Vivienda - CAVIPETROL"})
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        money = next(item for item in saved["normalizaciones"] if item["id_formateador"] == "FOR-002")
        self.assertEqual(money["valor_original"], "2.5E8")
        self.assertEqual(money["evidencias"][0]["pagina"], 2)
        self.assertIn("NORMALIZACION COMPLETADA", (root / "Logs" / "normalizacion.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
