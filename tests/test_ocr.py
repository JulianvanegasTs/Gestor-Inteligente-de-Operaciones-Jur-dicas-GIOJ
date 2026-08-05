"""Pruebas de la extracción documental GIOJ-004."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Codigo.config import load_configuration
from Codigo.expediente import DocumentoExpediente
from Codigo.ocr import OCRExtractionError, TextoExtraido, _extract_pdf, extract_expediente_text


def create_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    configuration = {
        "rutas": {"expedientes": "./Expedientes/", "logs": "./Logs/", "salida": "./Salida/"},
        "ocr": {"archivo_salida": "texto_extraido.json"},
    }
    (root / "Arquitectura" / "config.json").write_text(json.dumps(configuration), encoding="utf-8")
    return root


class OCRTests(unittest.TestCase):
    def test_scanned_pdf_uses_ocr_when_the_pdf_page_has_no_digital_text(self) -> None:
        root = create_project()
        source = root / "Expedientes" / "EXP-000" / "01_Documentos" / "escaneado.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"not-read-in-this-test")
        document = DocumentoExpediente("escaneado.pdf", "Expedientes/EXP-000/01_Documentos/escaneado.pdf", "PDF")
        rendered = root / "temporal" / "pagina-1.png"
        rendered.parent.mkdir()
        rendered.write_bytes(b"rendered")

        with (
            patch("Codigo.ocr._read_digital_pdf", return_value=[""]),
            patch("Codigo.ocr._render_pdf_page", return_value=rendered),
            patch("Codigo.ocr._run_tesseract", return_value=("texto OCR", 92.5)) as ocr,
        ):
            result = _extract_pdf(source, document, load_configuration(root))

        self.assertEqual((result[0].pagina, result[0].texto, result[0].metodo, result[0].confianza), (1, "texto OCR", "OCR PDF escaneado", 92.5))
        ocr.assert_called_once()
        self.assertFalse(rendered.parent.exists())

    def test_extract_expediente_text_preserves_document_page_and_text(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-001" / "01_Documentos"
        documents.mkdir(parents=True)
        (documents / "digital.pdf").write_bytes(b"not-read-in-this-test")
        (documents / "scan.png").write_bytes(b"not-read-in-this-test")

        def extract(_path: Path, document, _configuration):  # type: ignore[no-untyped-def]
            page = 2 if document.nombre == "digital.pdf" else 1
            return [TextoExtraido(document.ubicacion_original, page, f"texto {document.nombre}", "prueba")]

        with patch("Codigo.ocr._extract_document", side_effect=extract):
            result = extract_expediente_text(root, "EXP-001")

        self.assertEqual(
            [(item.documento, item.pagina, item.texto) for item in result.textos],
            [
                ("Expedientes/EXP-001/01_Documentos/digital.pdf", 2, "texto digital.pdf"),
                ("Expedientes/EXP-001/01_Documentos/scan.png", 1, "texto scan.png"),
            ],
        )
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(saved["textos"][0]["pagina"], 2)
        self.assertIn("TEXTO EXTRAIDO", (root / "Logs" / "ocr.log").read_text(encoding="utf-8"))

    def test_extract_expediente_text_records_one_document_error_and_continues(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-002" / "01_Documentos"
        documents.mkdir(parents=True)
        (documents / "fallido.pdf").write_bytes(b"not-read-in-this-test")
        (documents / "correcto.jpg").write_bytes(b"not-read-in-this-test")

        def extract(_path: Path, document, _configuration):  # type: ignore[no-untyped-def]
            if document.nombre == "fallido.pdf":
                raise OCRExtractionError("motor OCR no disponible")
            return [TextoExtraido(document.ubicacion_original, 1, "texto recuperado", "prueba")]

        with patch("Codigo.ocr._extract_document", side_effect=extract):
            result = extract_expediente_text(root, "EXP-002")

        self.assertEqual([item.texto for item in result.textos], ["texto recuperado"])
        self.assertEqual(result.errores[0].documento, "Expedientes/EXP-002/01_Documentos/fallido.pdf")
        self.assertIn("OCR ERROR", (root / "Logs" / "ocr.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
