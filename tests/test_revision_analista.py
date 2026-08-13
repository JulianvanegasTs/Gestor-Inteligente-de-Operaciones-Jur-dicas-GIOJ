"""Pruebas del doble análisis y del bloqueo previo a generación."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Codigo.revision_analista import (
    AnalystReviewError,
    authorize_document_generation,
    initialize_analyst_review,
    record_analyst_review,
)


def _project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    (root / "Plantillas").mkdir()
    (root / "Salida" / "EXP-REV").mkdir(parents=True)
    (root / "Plantillas" / "Certificado_Conformidad.docx").write_bytes(b"template")
    (root / "Plantillas" / "Certificado_No_Conformidad.docx").write_bytes(b"template")
    (root / "Arquitectura" / "config.json").write_text(
        json.dumps({
            "rutas": {"salida": "./Salida/", "plantillas": "./Plantillas/"},
            "archivos": {
                "plantilla_conformidad": "Certificado_Conformidad.docx",
                "plantilla_no_conformidad": "Certificado_No_Conformidad.docx",
            },
            "motor_juridico": {"archivo_salida": "resultado_juridico.json"},
            "revision_analista": {"archivo_salida": "revision_analista.json"},
        }),
        encoding="utf-8",
    )
    (root / "Salida" / "EXP-REV" / "resultado_juridico.json").write_text(
        json.dumps({
            "id_expediente": "EXP-REV",
            "resultado_preliminar": "No Conformidad",
        }),
        encoding="utf-8",
    )
    return root


class AnalystReviewTests(unittest.TestCase):
    def test_new_analysis_resets_review_and_blocks_generation(self) -> None:
        root = _project()

        review = initialize_analyst_review(root, "EXP-REV", "No Conformidad")

        self.assertEqual(review.estado, "Pendiente")
        self.assertFalse(review.generacion_habilitada)
        with self.assertRaisesRegex(AnalystReviewError, "confirme previamente"):
            authorize_document_generation(root, "EXP-REV")

    def test_rejection_requires_observation_and_keeps_generation_blocked(self) -> None:
        root = _project()
        initialize_analyst_review(root, "EXP-REV", "No Conformidad")

        with self.assertRaisesRegex(AnalystReviewError, "observación es obligatoria"):
            record_analyst_review(root, "EXP-REV", "Rechazado")
        review = record_analyst_review(
            root, "EXP-REV", "Rechazado", "Debe revisarse la evidencia de poder."
        )

        self.assertEqual(review.estado, "Rechazado")
        self.assertFalse(review.generacion_habilitada)

    def test_confirmation_authorizes_the_template_matching_the_result(self) -> None:
        root = _project()
        initialize_analyst_review(root, "EXP-REV", "No Conformidad")

        review = record_analyst_review(root, "EXP-REV", "Confirmado", "Revisión completada.")
        authorization = authorize_document_generation(root, "EXP-REV")

        self.assertTrue(review.generacion_habilitada)
        self.assertEqual(authorization.estado_revision, "Confirmado")
        self.assertEqual(authorization.resultado_confirmado, "No Conformidad")
        self.assertEqual(
            authorization.plantilla,
            "Plantillas/Certificado_No_Conformidad.docx",
        )


if __name__ == "__main__":
    unittest.main()
