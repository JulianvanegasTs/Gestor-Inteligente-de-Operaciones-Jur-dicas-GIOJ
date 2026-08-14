"""Regresión del ciclo integral: arquitectura, doble lectura y documentos oficiales."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from Codigo.clasificacion import DocumentProfile, _classify_document
from Codigo.config import ProjectConfiguration, load_configuration
from Codigo.extraccion import CriterioExtraccion, _Candidate, _criterion_accepts
from Codigo.generacion_documental import generate_official_document
from Codigo.ocr import _verified_ocr_file
from Codigo.revision_analista import (
    AnalystReviewError,
    initialize_analyst_review,
    record_analyst_review,
)
from Codigo.validacion import load_business_rules


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as package:
        return "\n".join(
            "".join(etree.fromstring(package.read(name)).itertext())
            for name in package.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        )


class IntegralCycleTests(unittest.TestCase):
    def test_manual_consecutive_rule_is_architectural_and_templates_have_no_marker(self) -> None:
        configuration = load_configuration(PROJECT_ROOT)
        rules = {item.id_regla: item for item in load_business_rules(configuration)}

        self.assertEqual(rules["DOC-002"].criterios["Tipo_Comparacion"], "Responsabilidad_Manual")
        self.assertEqual(rules["DOC-002"].criterios["Responsable"], "Analista")
        self.assertIn("no es extraído", rules["DOC-002"].criterios["Mensaje_Falla"])
        expected_hashes = {
            "Certificado_Conformidad.docx": "DC0EB02C552BE399756E7FF8BB49204E5F955FF27C176A12C9FB2D4CDE421DEB",
            "Certificado_No_Conformidad.docx": "E22F8FE9D33D42DECABC53B3368EA018374E9CD6D7044614E2EA305FA844B270",
        }
        for name, expected_hash in expected_hashes.items():
            template = PROJECT_ROOT / "Plantillas" / name
            self.assertEqual(_sha256(template), expected_hash)
            self.assertNotIn("{{CONSECUTIVO}}", _docx_text(template))

    def test_semantic_matricula_rejects_a_date_and_accepts_registral_context(self) -> None:
        criterion = CriterioExtraccion(
            "CRI-INM-003", "INM-003", "Certificado_Tradicion", "Escritura_Firma",
            ("MATRÍCULA INMOBILIARIA", "Nro Matrícula"), "Código registral",
            ("Radicación", "turno", "PIN", "cédula"), "Primera página", "Uno o varios",
            "Valor", "NORM_MATRICULA", 2, 0.9, "Revisión humana",
        )
        self.assertFalse(_criterion_accepts(
            _Candidate("05-2000", "Fecha: 05-2000", 120),
            "CERTIFICADO DE TRADICIÓN Fecha: 05-2000",
            criterion,
        ))
        self.assertTrue(_criterion_accepts(
            _Candidate("300-279737", "Nro Matrícula: 300-279737", 140),
            "MATRÍCULA INMOBILIARIA Nro Matrícula: 300-279737",
            criterion,
        ))

    def test_profile_classification_uses_physical_type_and_logical_role(self) -> None:
        profile = DocumentProfile(
            "PER-DOC_ID", "DOC_ID", "Documento de identidad",
            ("CÉDULA DE CIUDADANÍA",), ("APELLIDOS", "NOMBRES"), (), "Primera página", 85,
        )
        result = _classify_document(
            "CEDULA JAVIER.pdf",
            [{"pagina": 1, "texto": "CÉDULA DE CIUDADANÍA APELLIDOS GARCIA CARVAJAL NOMBRES JAVIER ALFONSO"}],
            (),
            (profile,),
            {"documento_logico_id": "LOG-0001", "rol_sugerido": "ROL_DOC_PRINCIPAL", "id_perfil_sugerido": "PER-DOC_ID"},
            {"ROL_DOC_PRINCIPAL": "Documento_Principal"},
        )
        self.assertEqual(result.codigo_tipo_documental, "DOC_ID")
        self.assertEqual(result.rol_documental, "Documento_Principal")
        self.assertGreaterEqual(result.confianza or 0, 85)

    def test_low_confidence_ocr_runs_a_second_read_and_keeps_both_evidences(self) -> None:
        configuration = ProjectConfiguration(
            PROJECT_ROOT,
            PROJECT_ROOT / "Arquitectura" / "config.json",
            {"ocr": {
                "idioma": "spa", "comando_tesseract": "tesseract", "registrar_confianza": True,
                "psm_primario": 3, "psm_secundario": 6, "doble_lectura_condicional": True,
                "umbral_confianza_segunda_lectura": 85, "umbral_coincidencia_segunda_lectura": 0.72,
            }},
        )
        with patch("Codigo.ocr._run_tesseract", side_effect=[
            ("CEDULA 91292114", 70.0), ("CEDULA 91.292.114", 92.0),
        ]) as mocked:
            result = _verified_ocr_file(Path("pagina.png"), configuration)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result[0], "CEDULA 91.292.114")
        self.assertEqual(result[2], "CEDULA 91292114")
        self.assertIsInstance(result[4], float)

    def test_individual_review_is_required_before_global_confirmation(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "Arquitectura").mkdir()
        (root / "Plantillas").mkdir()
        output = root / "Salida" / "EXP-REV"
        output.mkdir(parents=True)
        for name in ("Certificado_Conformidad.docx", "Certificado_No_Conformidad.docx"):
            (root / "Plantillas" / name).write_bytes(b"plantilla")
        (root / "Arquitectura" / "config.json").write_text(json.dumps({
            "rutas": {"salida": "./Salida/", "plantillas": "./Plantillas/"},
            "archivos": {
                "plantilla_conformidad": "Certificado_Conformidad.docx",
                "plantilla_no_conformidad": "Certificado_No_Conformidad.docx",
            },
            "motor_juridico": {"archivo_salida": "resultado_juridico.json"},
            "revision_analista": {
                "archivo_salida": "revision_analista.json",
                "revision_individual_obligatoria": True,
                "estados_revision_validacion": ["Pendiente", "Confirmada", "Observada"],
            },
        }), encoding="utf-8")
        (output / "resultado_juridico.json").write_text(json.dumps({
            "id_expediente": "EXP-REV", "resultado_preliminar": "No Conformidad",
            "evaluaciones_reglas": [
                {"id_regla": "OBL-001", "resultado_validacion": "No cumple"},
                {"id_regla": "DOC-002", "resultado_validacion": "No aplica"},
            ],
        }), encoding="utf-8")
        review = initialize_analyst_review(root, "EXP-REV", "No Conformidad")
        self.assertEqual(review.validaciones_pendientes, 1)
        with self.assertRaisesRegex(AnalystReviewError, "Revise individualmente"):
            record_analyst_review(root, "EXP-REV", "Confirmado")
        confirmed = record_analyst_review(root, "EXP-REV", "Confirmado", validations=[
            {"id_regla": "OBL-001", "estado_revision": "Confirmada", "observacion": ""},
            {"id_regla": "DOC-002", "estado_revision": "Confirmada", "observacion": ""},
        ])
        self.assertTrue(confirmed.generacion_habilitada)
        self.assertEqual(confirmed.validaciones_pendientes, 0)

    def test_generates_conformity_and_nonconformity_without_changing_templates(self) -> None:
        for result_name in ("Conformidad", "No Conformidad"):
            with self.subTest(result=result_name):
                root = Path(tempfile.mkdtemp())
                (root / "Arquitectura").mkdir()
                (root / "Plantillas").mkdir()
                (root / "Salida" / "EXP-GEN").mkdir(parents=True)
                shutil.copy2(PROJECT_ROOT / "Arquitectura" / "Arquitectura.xlsx", root / "Arquitectura" / "Arquitectura.xlsx")
                for name in ("Certificado_Conformidad.docx", "Certificado_No_Conformidad.docx"):
                    shutil.copy2(PROJECT_ROOT / "Plantillas" / name, root / "Plantillas" / name)
                config = json.loads((PROJECT_ROOT / "Arquitectura" / "config.json").read_text(encoding="utf-8"))
                config["rutas"] = {
                    "arquitectura": "./Arquitectura/Arquitectura.xlsx", "plantillas": "./Plantillas/",
                    "salida": "./Salida/", "logs": "./Logs/", "expedientes": "./Expedientes/",
                    "conocimiento": "./Conocimiento/", "codigo": "./Codigo/",
                }
                (root / "Arquitectura" / "config.json").write_text(json.dumps(config), encoding="utf-8")
                output = root / "Salida" / "EXP-GEN"
                fields = {
                    "PER-002": "JAVIER ALFONSO GARCIA CARVAJAL", "PER-003": "CÉDULA DE CIUDADANÍA",
                    "PER-004": "91292114", "CRE-004": "$ 250.000.000", "CRE-003": "Vivienda",
                    "INM-003": "300-279737", "ESC-003": "123", "ESC-004": "13/08/2026",
                    "ESC-005": "Notaría Primera", "ESC-006": "Bogotá D.C.",
                }
                (output / "extraccion_documental.json").write_text(json.dumps({
                    "id_expediente": "EXP-GEN",
                    "campos": [
                        {"id_campo": key, "valores": [{"valor_encontrado": value}]}
                        for key, value in fields.items()
                    ],
                }, ensure_ascii=False), encoding="utf-8")
                (output / "resultado_juridico.json").write_text(json.dumps({
                    "id_expediente": "EXP-GEN", "resultado_preliminar": result_name,
                    "trazabilidad": {"inconsistencias": [{
                        "id_regla": "OBL-001", "campo": "Matrícula",
                        "observacion": "Corregir el valor discordante.",
                    }] if result_name == "No Conformidad" else []},
                }, ensure_ascii=False), encoding="utf-8")
                (output / "revision_analista.json").write_text(json.dumps({
                    "id_expediente": "EXP-GEN", "resultado_preliminar": result_name,
                    "estado": "Confirmado", "observacion": "Revisado", "fecha_revision": "2026-08-13",
                    "generacion_habilitada": True,
                }), encoding="utf-8")
                template_name = "Certificado_Conformidad.docx" if result_name == "Conformidad" else "Certificado_No_Conformidad.docx"
                template = root / "Plantillas" / template_name
                before = _sha256(template)

                def fake_pdf(_configuration: object, _word: Path, pdf: Path) -> None:
                    pdf.write_bytes(b"%PDF-1.4\n% regression\n")

                with patch("Codigo.generacion_documental._convert_pdf", side_effect=fake_pdf):
                    generated = generate_official_document(root, "EXP-GEN")
                self.assertEqual(_sha256(template), before)
                word = root / generated.archivo_word
                text = _docx_text(word)
                self.assertIn("JAVIER ALFONSO GARCIA CARVAJAL", text)
                self.assertNotIn("{{", text)
                self.assertIn("manual", generated.consecutivo)
                self.assertTrue((root / generated.archivo_pdf).is_file())

    def test_local_corpus_has_verified_positive_and_negative_cases(self) -> None:
        corpus = PROJECT_ROOT / "Expedientes" / "Pruebas"
        if not corpus.is_dir():
            self.skipTest("El corpus sensible es local y está excluido de Git")
        conform = sorted((corpus / "Casos_Conformidad").glob("CON-*"))
        nonconform = sorted((corpus / "Casos_No_Conformidad").glob("NC-*"))
        self.assertEqual(len(conform), 10)
        self.assertEqual(len(nonconform), 10)
        negative_validations = 0
        for expected_result, cases in (("Conformidad", conform), ("No Conformidad", nonconform)):
            for case in cases:
                structured = json.loads((case / "02_Datos_estructurados" / "datos_estructurados.json").read_text(encoding="utf-8"))
                expected = json.loads((case / "03_Resultados" / "resultado_esperado.json").read_text(encoding="utf-8"))
                self.assertEqual(structured["verificacion"]["estado"], "Verificado")
                self.assertEqual(expected["verificacion"]["estado"], "Verificado")
                self.assertEqual(expected["resultado_juridico_esperado"], expected_result)
                if expected_result == "No Conformidad":
                    negative_validations += len(expected.get("validaciones", []))
        self.assertEqual(negative_validations, 65)
        identity = (conform[4] / "02_Datos_estructurados" / "datos_estructurados.json").read_text(encoding="utf-8")
        self.assertIn("JAVIER ALFONSO", identity)
        self.assertIn("91,292,114", identity)


if __name__ == "__main__":
    unittest.main()
