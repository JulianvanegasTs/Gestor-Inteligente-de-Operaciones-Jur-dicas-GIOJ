"""Pruebas del motor jurídico GIOJ-009."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.motor_juridico import (
    LegalEngineError,
    _build_traceability,
    _legal_concept,
    apply_legal_engine,
)
from Codigo.extraccion import CampoExtraccion
from Codigo.validacion import ReglaNegocio


def _workbook(path: Path) -> None:
    sheets = {
        "01_Campos_Extraccion": [
            ["ID_Campo", "Nivel", "Campo_Padre", "Entidad", "Campo", "Obligatorio"],
            ["ENT-001", "Entidad", "", "Persona", "Persona", "No"],
        ],
        "04_Reglas_Negocio": [
            ["ID_Regla", "Tipo_Regla", "Apoderado", "Estado", "Fuente_Regla"],
            ["REG-001", "Poder_Autorizado", "ANA PÉREZ", "Vigente", "Fuente oficial"],
            ["REG-002", "Poder_Autorizado", "JUAN PÉREZ", "No_Autorizado", "Fuente oficial"],
        ],
        "05_Extraccion_Documental": [
            ["ID_Extraccion", "ID_Campo", "Documento_Origen"],
            ["EXT-001", "ENT-001", "Escritura_Firma"],
        ],
    }

    def sheet_xml(rows: list[list[str]]) -> str:
        sheet_rows = []
        for row_number, row in enumerate(rows, 1):
            cells = "".join(
                f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                for column, value in enumerate(row)
            )
            sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
        return (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(sheet_rows)
            + "</sheetData></worksheet>"
        )

    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>'
            + "".join(
                f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
                for index, name in enumerate(sheets, 1)
            )
            + "</sheets></workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
                for index in range(1, len(sheets) + 1)
            )
            + "</Relationships>",
        )
        for index, rows in enumerate(sheets.values(), 1):
            workbook.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))


def _project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    (root / "Salida" / "EXP-009").mkdir(parents=True)
    _workbook(root / "Arquitectura" / "Arquitectura.xlsx")
    (root / "Arquitectura" / "config.json").write_text(
        json.dumps(
            {
                "rutas": {
                    "arquitectura": "./Arquitectura/Arquitectura.xlsx",
                    "salida": "./Salida/",
                    "logs": "./Logs/",
                },
                "hojas": {
                    "campos": "01_Campos_Extraccion",
                    "reglas": "04_Reglas_Negocio",
                    "extraccion": "05_Extraccion_Documental",
                },
                "validacion": {"archivo_salida": "validaciones.json"},
                "motor_juridico": {"archivo_salida": "resultado_juridico.json"},
            }
        ),
        encoding="utf-8",
    )
    return root


def _validations(root: Path, first: str, second: str) -> None:
    payload = {
        "id_expediente": "EXP-009",
        "origen_reglas": "04_Reglas_Negocio",
        "validaciones": [
            {"id_regla": "REG-001", "tipo_regla": "Poder_Autorizado", "estado": first},
            {"id_regla": "REG-002", "tipo_regla": "Poder_Autorizado", "estado": second},
        ],
    }
    (root / "Salida" / "EXP-009" / "validaciones.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class LegalEngineTests(unittest.TestCase):
    def test_legal_concept_does_not_duplicate_traceability(self) -> None:
        concept = _legal_concept("No Conformidad", {
            "MIN-001": {
                "id_regla": "MIN-001",
                "estado": "No cumple",
                "comparaciones": [{
                    "documento_validado": "escritura_firma.pdf",
                    "pagina_validada": 4,
                    "valor_esperado": "Texto de la minuta",
                    "valor_encontrado": "Texto diferente",
                    "estado_interfaz": "No validado",
                }],
            },
        })

        self.assertIn("concluye No Conformidad", concept)
        self.assertNotIn("escritura_firma.pdf", concept)
        self.assertNotIn("Texto de la minuta", concept)

    def test_traceability_registers_every_decision_and_formats_inconsistency(self) -> None:
        rule = ReglaNegocio(
            "MIN-001",
            "Formato_Minuta",
            "Conocimiento/Minutas/Minuta_hipoteca.docx",
            {"ID_Campo_Clausula": "MIN-CLA-001"},
        )
        traceability = _build_traceability(
            "No Conformidad",
            (rule,),
            {
                "MIN-001": {
                    "id_regla": "MIN-001",
                    "estado": "No cumple",
                    "observacion": "La cláusula no corresponde.",
                    "comparaciones": [
                        {
                            "documento_validado": "escritura_firma.pdf",
                            "pagina_validada": 4,
                            "valor_esperado": "Texto de la minuta",
                            "valor_encontrado": ["Texto diferente"],
                            "estado": "No cumple",
                            "observacion": "El valor encontrado no coincide.",
                        }
                    ],
                }
            },
        )

        self.assertEqual(len(traceability.registros), 1)
        inconsistency = traceability.inconsistencias[0]
        self.assertIsInstance(inconsistency.pagina, int)
        self.assertEqual(inconsistency.pagina, 4)
        self.assertEqual(inconsistency.documento, "escritura_firma.pdf")
        self.assertEqual(inconsistency.campo, "MIN-CLA-001")
        self.assertEqual(inconsistency.valor_encontrado, "Texto diferente")
        self.assertEqual(inconsistency.valor_esperado, "Texto de la minuta")
        self.assertEqual(inconsistency.resultado, "No coincide")
        self.assertEqual(inconsistency.observacion, "El valor encontrado no coincide.")
        self.assertEqual(inconsistency.estado_validacion, "No cumple")
        self.assertIn("En mérito de lo expuesto", traceability.sintesis_dictamen)

    def test_traceability_exposes_every_mandatory_field_with_compared_source_page(self) -> None:
        field = CampoExtraccion(
            "PER-001",
            "Atributo",
            "Persona",
            "Persona",
            "Tipo_Documento",
            None,
            "Texto",
            None,
            "No",
            "Sí",
            None,
            "Sí",
        )
        rule = ReglaNegocio(
            "OBL-PER-001",
            "Campo_Obligatorio",
            "01_Campos_Extraccion",
            {
                "ID_Campo_Clausula": "PER-001",
                "Documento_Comparado": "Documento_Identidad",
            },
        )
        traceability = _build_traceability(
            "Conformidad",
            (rule,),
            {
                "OBL-PER-001": {
                    "estado": "Cumple",
                    "comparaciones": [{
                        "campo": "PER-001",
                        "documento_validado": "escritura_firma.pdf",
                        "pagina_validada": 5,
                        "documento_comparado": "cedula.pdf",
                        "pagina_comparada": 2,
                        "valor_encontrado": ["CÉDULA DE CIUDADANÍA"],
                        "valor_esperado": "CÉDULA DE CIUDADANÍA",
                        "estado": "Cumple",
                    }],
                }
            },
            (field,),
        )

        self.assertEqual(len(traceability.campos_obligatorios), 1)
        visible = traceability.campos_obligatorios[0]
        self.assertEqual(visible.datos, "Tipo_Documento")
        self.assertEqual(visible.documento_contrastado, "cedula.pdf")
        self.assertEqual(visible.pagina, 2)
        self.assertIsInstance(visible.pagina, int)
        self.assertEqual(visible.valor_encontrado, "CÉDULA DE CIUDADANÍA")
        self.assertEqual(visible.valor_esperado, "CÉDULA DE CIUDADANÍA")
        self.assertEqual(visible.resultado, "Coincide")

    def test_conformity_uses_the_matching_current_alternative(self) -> None:
        root = _project()
        _validations(root, "Cumple", "No cumple")

        result = apply_legal_engine(root, "EXP-009")

        self.assertEqual(result.resultado, "Conformidad")
        self.assertEqual(result.resumen.total_reglas_definidas, 2)
        self.assertEqual(result.resumen.total_reglas_evaluadas, 2)
        self.assertEqual(result.resultados_por_tipo[0].reglas_coincidentes, ("REG-001",))
        self.assertEqual(result.evaluaciones_reglas[0].efecto, "Coincidencia habilitante")
        self.assertEqual(result.observaciones, ())
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(saved["resultado"], "Conformidad")
        self.assertEqual(saved["origen_reglas"], "04_Reglas_Negocio")
        self.assertEqual(saved["origen_validaciones"], "Salida/EXP-009/validaciones.json")
        self.assertEqual(len(saved["trazabilidad"]["registros"]), 2)
        self.assertIsNotNone(result.trazabilidad)
        self.assertIn(
            "MOTOR JURIDICO COMPLETADO",
            (root / "Logs" / "motor_juridico.log").read_text(encoding="utf-8"),
        )

    def test_non_conformity_when_the_matching_alternative_is_not_current(self) -> None:
        root = _project()
        _validations(root, "No cumple", "Cumple")

        result = apply_legal_engine(root, "EXP-009")

        self.assertEqual(result.resultado, "No Conformidad")
        self.assertEqual(result.resultados_por_tipo[0].estado, "No cumple")
        self.assertEqual(result.evaluaciones_reglas[1].estado_configurado, "No_Autorizado")
        self.assertEqual(result.evaluaciones_reglas[1].efecto, "Coincidencia no habilitante")
        self.assertEqual(result.observaciones[0].numero, 1)
        self.assertEqual(result.observaciones[0].reglas_relacionadas, ("REG-002",))

    def test_non_conformity_when_there_is_not_enough_information(self) -> None:
        root = _project()
        _validations(root, "No existe información", "No existe información")

        result = apply_legal_engine(root, "EXP-009")

        self.assertEqual(result.resultado, "No Conformidad")
        self.assertEqual(result.resultados_por_tipo[0].estado, "No existe información")
        self.assertEqual(result.resumen.tipos_no_existe_informacion, 1)

    def test_non_conformity_when_matches_have_conflicting_configured_states(self) -> None:
        root = _project()
        _validations(root, "Cumple", "Cumple")

        result = apply_legal_engine(root, "EXP-009")

        self.assertEqual(result.resultado, "No Conformidad")
        self.assertEqual(result.resultados_por_tipo[0].reglas_coincidentes, ("REG-001", "REG-002"))
        self.assertEqual(
            result.resultados_por_tipo[0].estados_configurados,
            ("Vigente", "No_Autorizado"),
        )

    def test_rejects_incomplete_rule_coverage(self) -> None:
        root = _project()
        _validations(root, "Cumple", "No cumple")
        path = root / "Salida" / "EXP-009" / "validaciones.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["validaciones"].pop()
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(LegalEngineError, "faltan REG-002"):
            apply_legal_engine(root, "EXP-009")

    def test_rejects_an_expediente_outside_the_configured_output(self) -> None:
        root = _project()

        with self.assertRaisesRegex(LegalEngineError, "identificador del expediente no es válido"):
            apply_legal_engine(root, "../EXP-009")


if __name__ == "__main__":
    unittest.main()
