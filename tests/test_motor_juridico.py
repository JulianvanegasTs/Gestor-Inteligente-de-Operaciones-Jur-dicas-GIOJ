"""Pruebas del motor jurídico GIOJ-009."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.motor_juridico import LegalEngineError, _legal_concept, apply_legal_engine


def _workbook(path: Path) -> None:
    rows = [
        ["ID_Regla", "Tipo_Regla", "Apoderado", "Estado", "Fuente_Regla"],
        ["REG-001", "Poder_Autorizado", "ANA PÉREZ", "Vigente", "Fuente oficial"],
        ["REG-002", "Poder_Autorizado", "JUAN PÉREZ", "No_Autorizado", "Fuente oficial"],
    ]
    sheet_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="04_Reglas_Negocio" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(sheet_rows)
            + "</sheetData></worksheet>",
        )


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
                "hojas": {"reglas": "04_Reglas_Negocio"},
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
    def test_legal_concept_enumerates_inconsistencies_with_source_file(self) -> None:
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

        self.assertIn("1. MIN-001: archivo escritura_firma.pdf, página 4", concept)
        self.assertIn("valor esperado: Texto de la minuta", concept)
        self.assertIn("valor encontrado: Texto diferente", concept)

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
