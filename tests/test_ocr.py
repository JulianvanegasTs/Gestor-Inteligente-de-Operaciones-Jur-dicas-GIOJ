"""Pruebas de la extracción documental GIOJ-004."""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from Codigo.config import load_configuration
from Codigo.expediente import DocumentoExpediente
from Codigo.ocr import OCRExtractionError, TextoExtraido, _extract_pdf, _run_tesseract, extract_expediente_text
from Codigo.web import create_server


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
    def test_analysis_endpoint_runs_ocr_and_reports_the_output_file(self) -> None:
        root = create_project()
        documents = root / "Expedientes" / "EXP-WEB" / "01_Documentos"
        documents.mkdir(parents=True)
        (documents / "imagen.png").write_bytes(b"not-read-in-this-test")
        server = create_server(root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address, port = server.server_address[:2]
            request = Request(
                f"http://{address}:{port}/api/analisis/iniciar",
                data=json.dumps({"id_expediente": "EXP-WEB"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            extracted = TextoExtraido(
                "Expedientes/EXP-WEB/01_Documentos/imagen.png", 1, "texto visible", "OCR imagen", 95.0
            )
            with patch("Codigo.ocr._extract_document", return_value=[extracted]):
                with urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            with urlopen(
                f"http://{address}:{port}/api/analisis/progreso?id_expediente=EXP-WEB"
            ) as response:
                progress = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(payload["mensaje"], "Texto documental extraído.")
        self.assertEqual(payload["ocr"]["archivo_salida"], "Salida/EXP-WEB/texto_extraido.json")
        self.assertIn("Resultado: Salida/EXP-WEB/texto_extraido.json", payload["detalle"])
        output = json.loads((root / payload["ocr"]["archivo_salida"]).read_text(encoding="utf-8"))
        self.assertEqual(output["textos"][0]["documento"], extracted.documento)
        self.assertEqual(output["textos"][0]["pagina"], 1)
        self.assertEqual(output["textos"][0]["texto"], "texto visible")
        self.assertEqual(output["textos"][0]["metodo"], "OCR imagen")
        self.assertEqual(output["textos"][0]["confianza"], 95.0)
        self.assertEqual(progress["estado"], "completado")
        self.assertEqual(progress["archivo_salida"], "Salida/EXP-WEB/texto_extraido.json")
        self.assertEqual(progress["completadas"], 1)
        self.assertEqual(progress["total"], 1)

    def test_official_interface_contains_accessible_progress_bar_and_time_estimate(self) -> None:
        interface = (Path(__file__).parent.parent / "Programa" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="analysis-progress"', interface)
        self.assertIn('role="progressbar"', interface)
        self.assertIn('id="progress-percent"', interface)
        self.assertIn('id="progress-remaining"', interface)
        self.assertIn("Restante estimado", interface)

    def test_tesseract_extracts_text_and_confidence_in_one_pass(self) -> None:
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90.0\tTexto\n"
            "5\t1\t1\t1\t1\t2\t10\t0\t10\t10\t80.0\treconocido\n"
        )
        completed = subprocess.CompletedProcess([], 0, stdout=tsv, stderr="")
        with (
            patch("Codigo.ocr.shutil.which", return_value="tesseract") as which,
            patch("Codigo.ocr.subprocess.run", return_value=completed) as run,
        ):
            text, confidence = _run_tesseract(Path("pagina.png"), "spa", "tesseract", True)

        self.assertEqual(text, "Texto reconocido")
        self.assertEqual(confidence, 85.0)
        which.assert_called_once_with("tesseract")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], "tsv")

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

        def extract(_path: Path, document, _configuration, _progress):  # type: ignore[no-untyped-def]
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

        def extract(_path: Path, document, _configuration, _progress):  # type: ignore[no-untyped-def]
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
