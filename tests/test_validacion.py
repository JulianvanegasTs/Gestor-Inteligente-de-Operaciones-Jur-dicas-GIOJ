"""Pruebas del intérprete de 04_Reglas_Negocio para GIOJ-008."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.validacion import (
    ReglaNegocio,
    ResultadoValidacion,
    _documents_of_type,
    _matches_nearby,
    _matching_page,
    _validate_consolidation,
    validate_expediente_data,
)


def _workbook(path: Path) -> None:
    rows = [
        ["ID_Regla", "Tipo_Regla", "Apoderado", "Numero_Documento", "Fecha_Poder", "Notaria", "Fuente_Regla"],
        ["REG-001", "Poder_Autorizado", "ANA PÉREZ", "4.0327918E7", "46105", "27", "Fuente oficial"],
        ["REG-002", "Poder_Autorizado", "OTRA PERSONA", "4.0327918E7", "46105", "27", "Fuente oficial"],
        ["REG-003", "Poder_Autorizado", "", "", "", "28", "Fuente oficial"],
    ]
    sheet_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="04_Reglas_Negocio" sheetId="1" r:id="rId1"/></sheets></workbook>')
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        workbook.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>")


def _structured_workbook(path: Path) -> None:
    rows = [
        ["ID_Regla", "Tipo_Regla", "ID_Campo_Clausula", "Documento_Validado", "Documento_Comparado", "Fuente_Valor_Esperado", "Tipo_Comparacion", "Estado", "Fuente_Regla"],
        ["DOC-001", "Integridad_Documental", "", "Escritura_Firma", "Clasificacion_Documental", "Escritura_Firma", "Documento_Unico", "Vigente", "Arquitectura.xlsx"],
        ["OBL-INM-003", "Campo_Obligatorio", "INM-003", "Escritura_Firma", "Certificado_Tradicion", "INM-003", "Campo_Obligatorio_Comparado", "Vigente", "01_Campos_Extraccion"],
    ]
    sheet_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="04_Reglas_Negocio" sheetId="1" r:id="rId1"/></sheets></workbook>')
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        workbook.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>")


class ValidationTests(unittest.TestCase):
    def test_consolidation_only_blocks_on_applicable_blocking_rules(self) -> None:
        blocking = ReglaNegocio(
            "REG-BLOQ", "Campo_Obligatorio", "Arquitectura.xlsx",
            {"Severidad": "Bloqueante", "Estado": "Vigente"},
        )
        warning = ReglaNegocio(
            "REG-ADV", "Calidad_Documental", "Arquitectura.xlsx",
            {"Severidad": "Advertencia", "Estado": "Vigente"},
        )
        consolidation = ReglaNegocio(
            "CON-001", "Consolidacion_Resultados", "Arquitectura.xlsx",
            {"Tipo_Comparacion": "Consolidacion_Bloqueantes", "Severidad": "Bloqueante"},
        )
        completed = {
            "REG-BLOQ": ResultadoValidacion("REG-BLOQ", "Campo_Obligatorio", "Arquitectura.xlsx", "Cumple", (), ""),
            "REG-ADV": ResultadoValidacion("REG-ADV", "Calidad_Documental", "Arquitectura.xlsx", "No cumple", (), ""),
        }

        result = _validate_consolidation(
            consolidation, (blocking, warning, consolidation), completed
        )

        self.assertEqual(result.estado, "Cumple")

    def test_consolidation_rejects_missing_information_in_a_blocking_rule(self) -> None:
        blocking = ReglaNegocio(
            "REG-BLOQ", "Campo_Obligatorio", "Arquitectura.xlsx",
            {"Severidad": "Bloqueante", "Estado": "Vigente"},
        )
        consolidation = ReglaNegocio(
            "CON-001", "Consolidacion_Resultados", "Arquitectura.xlsx",
            {"Tipo_Comparacion": "Consolidacion_Bloqueantes", "Severidad": "Bloqueante"},
        )
        completed = {
            "REG-BLOQ": ResultadoValidacion(
                "REG-BLOQ", "Campo_Obligatorio", "Arquitectura.xlsx",
                "No existe información", (), "Falta evidencia.",
            ),
        }

        result = _validate_consolidation(
            consolidation, (blocking, consolidation), completed
        )

        self.assertEqual(result.estado, "No cumple")
        self.assertIn("REG-BLOQ=No existe información", result.comparaciones[0].valor_encontrado)

    def test_accepts_architectural_document_names_with_connectors(self) -> None:
        classifications = {"CEDULA JAVIER.pdf": "Documento de Identidad"}

        self.assertEqual(
            _documents_of_type(classifications, "Documento_Identidad"),
            ("CEDULA JAVIER.pdf",),
        )

    def test_matches_formatted_identity_number_and_nearby_document_evidence(self) -> None:
        pages = [{"pagina": 1, "texto": "DOCUMENTO DE IDENTIFICACIÓN: C.C. 91.292.114"}]

        page, _text = _matching_page("91292114", pages)

        self.assertEqual(page, 1)
        self.assertTrue(_matches_nearby("Escritura Firma", "firma de esta escritura"))
        self.assertFalse(
            _matches_nearby(
                "Escritura Firma",
                "firma del registrador con abundante contenido intermedio que luego cita una escritura",
            )
        )

    def test_reads_each_rule_and_preserves_comparison_evidence(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "Arquitectura").mkdir()
        (root / "Salida" / "EXP-008").mkdir(parents=True)
        _workbook(root / "Arquitectura" / "Arquitectura.xlsx")
        (root / "Arquitectura" / "config.json").write_text(json.dumps({
            "rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "salida": "./Salida/", "logs": "./Logs/"},
            "hojas": {"reglas": "04_Reglas_Negocio"},
            "extraccion": {"archivo_salida": "extraccion_documental.json"},
            "validacion": {"archivo_salida": "validaciones.json"},
        }), encoding="utf-8")
        (root / "Salida" / "EXP-008" / "extraccion_documental.json").write_text(json.dumps({
            "id_expediente": "EXP-008",
            "campos": [
                {"id_campo": "POD-004", "campo": "Apoderado", "valores": [{"valor_encontrado": "ANA PEREZ", "documento": "poder.pdf", "pagina": 3}]},
                {"id_campo": "PER-004", "campo": "Numero_Documento", "valores": [{"valor_encontrado": "40.327.918", "documento": "poder.pdf", "pagina": 3}]},
                {"id_campo": "POD-005", "campo": "Fecha_Poder", "valores": [{"valor_encontrado": "2026-03-24", "documento": "poder.pdf", "pagina": 3}]},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        result = validate_expediente_data(root, "EXP-008")

        self.assertEqual(result.resumen.total_validaciones, 3)
        self.assertEqual([item.estado for item in result.validaciones], ["Cumple", "No cumple", "No existe información"])
        first = result.validaciones[0]
        self.assertEqual(first.comparaciones[0].documento_origen, ("poder.pdf",))
        self.assertEqual(first.comparaciones[0].pagina_origen, (3,))
        self.assertEqual(first.comparaciones[1].estado, "Cumple")
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(saved["origen_reglas"], "04_Reglas_Negocio")
        self.assertEqual(saved["resumen"]["no_cumple"], 1)
        self.assertIn("VALIDACION COMPLETADA", (root / "Logs" / "validacion.log").read_text(encoding="utf-8"))

    def test_compares_mandatory_source_value_with_escritura_and_exposes_interface_trace(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "Arquitectura").mkdir()
        output = root / "Salida" / "EXP-011"
        output.mkdir(parents=True)
        _structured_workbook(root / "Arquitectura" / "Arquitectura.xlsx")
        (root / "Arquitectura" / "config.json").write_text(json.dumps({
            "rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "salida": "./Salida/", "logs": "./Logs/"},
            "hojas": {"reglas": "04_Reglas_Negocio"},
            "ocr": {"archivo_salida": "texto_extraido.json"},
            "extraccion": {"archivo_salida": "extraccion_documental.json"},
            "validacion": {"archivo_salida": "validaciones.json"},
        }), encoding="utf-8")
        source_document = "Expedientes/EXP-011/01_Documentos/ctl.pdf"
        escritura_document = "Expedientes/EXP-011/01_Documentos/escritura.pdf"
        (output / "clasificacion_documental.json").write_text(json.dumps({
            "id_expediente": "EXP-011",
            "documentos": [
                {"documento": source_document, "tipo_documental": "Certificado_Tradicion"},
                {"documento": escritura_document, "tipo_documental": "Escritura_Firma"},
            ],
        }), encoding="utf-8")
        (output / "texto_extraido.json").write_text(json.dumps({
            "id_expediente": "EXP-011",
            "textos": [{"documento": escritura_document, "pagina": 4, "texto": "Folio de matrícula inmobiliaria 50C-123456"}],
        }), encoding="utf-8")
        (output / "extraccion_documental.json").write_text(json.dumps({
            "id_expediente": "EXP-011",
            "campos": [{"id_campo": "INM-003", "campo": "Matricula", "valores": [{"valor_encontrado": "50C-123456", "documento": source_document, "pagina": 2}]}],
        }), encoding="utf-8")

        result = validate_expediente_data(root, "EXP-011")

        self.assertEqual([item.estado for item in result.validaciones], ["Cumple", "Cumple"])
        comparison = result.validaciones[1].comparaciones[0]
        self.assertEqual(comparison.documento_validado, escritura_document)
        self.assertEqual(comparison.pagina_validada, 4)
        self.assertEqual(comparison.documento_comparado, source_document)
        self.assertEqual(comparison.pagina_comparada, 2)
        self.assertEqual(comparison.estado_interfaz, "Validado")


if __name__ == "__main__":
    unittest.main()
