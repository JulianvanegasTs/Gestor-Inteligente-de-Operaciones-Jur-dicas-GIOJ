"""Pruebas de la extracción documental GIOJ-004."""

from __future__ import annotations

import json
import io
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from Codigo.config import load_configuration
from Codigo.clasificacion import DocumentoClasificado, ResultadoClasificacion
from Codigo.extraccion import ResultadoExtraccion
from Codigo.expediente import DocumentoExpediente, create_selected_file
from Codigo.motor_juridico import (
    RegistroTrazabilidad,
    ResultadoMotorJuridico,
    ResultadoTrazabilidad,
    ResumenMotorJuridico,
)
from Codigo.normalizacion import ResultadoNormalizacion, ResumenNormalizacion
from Codigo.ocr import (
    OCRExtractionError,
    ResultadoOCR,
    TextoExtraido,
    _extract_pdf,
    _run_tesseract,
    extract_expediente_text,
    extract_selected_files_text,
)
from Codigo.validacion import ResultadoValidaciones, ResumenValidacion
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
    def test_selected_docx_is_processed_from_memory_without_creating_a_source_copy(self) -> None:
        root = create_project()
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Escritura para firma</w:t></w:r></w:p></w:body></w:document>",
            )
        selected = create_selected_file("escritura.docx", content.getvalue())

        result = extract_selected_files_text(root, "SEL-MEMORIA", (selected,))

        self.assertEqual(result.textos[0].documento, "escritura.docx")
        self.assertEqual(result.textos[0].texto, "Escritura para firma")
        self.assertFalse((root / "Expedientes").exists())
        self.assertTrue((root / result.archivo_salida).is_file())

    def test_file_selection_endpoint_accepts_multipart_and_does_not_create_copies(self) -> None:
        root = create_project()
        server = create_server(root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        boundary = "gioj-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="archivos"; filename="escritura.docx"\r\n'
            "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
        ).encode("utf-8") + b"contenido-seleccionado" + f"\r\n--{boundary}--\r\n".encode("utf-8")
        try:
            address, port = server.server_address[:2]
            request = Request(
                f"http://{address}:{port}/api/archivos/seleccion",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
            selection_id = payload["seleccion"]["id"]
            extracted = TextoExtraido("escritura.docx", 1, "texto", "Documento Word")
            classification = ResultadoClasificacion(
                selection_id,
                (DocumentoClasificado("escritura.docx", "Escritura_Firma", "ESC-FIR", "Clasificado", (), ""),),
                f"Salida/{selection_id}/clasificacion_documental.json",
            )
            with (
                patch(
                    "Codigo.web.extract_selected_files_text",
                    return_value=ResultadoOCR(selection_id, (extracted,), (), f"Salida/{selection_id}/texto_extraido.json"),
                ) as memory_ocr,
                patch("Codigo.web.classify_expediente_documents", return_value=classification) as classify,
                patch("Codigo.web.extract_expediente_data", return_value=ResultadoExtraccion(selection_id, (), (), f"Salida/{selection_id}/extraccion_documental.json")),
                patch("Codigo.web.normalize_expediente_data", return_value=ResultadoNormalizacion(selection_id, (), (), f"Salida/{selection_id}/normalizacion_documental.json", ResumenNormalizacion(0, 0, 0, ()))),
                patch("Codigo.web.validate_expediente_data", return_value=ResultadoValidaciones(selection_id, (), f"Salida/{selection_id}/validaciones_documentales.json", ResumenValidacion(0, 0, 0, 0, 0, 0))),
                patch("Codigo.web.apply_legal_engine", return_value=ResultadoMotorJuridico(selection_id, "Conformidad", (), (), (), f"Salida/{selection_id}/resultado_juridico.json", ResumenMotorJuridico(0, 0, 0, 0, 0, 0, 0))),
            ):
                analysis_request = Request(
                    f"http://{address}:{port}/api/analisis/iniciar",
                    data=json.dumps({"id_expediente": selection_id}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(analysis_request) as response:
                    analysis = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertTrue(payload["seleccion"]["id"].startswith("SEL-"))
        self.assertEqual(payload["seleccion"]["documentos"][0]["nombre"], "escritura.docx")
        self.assertIn("solo en memoria", payload["detalle"])
        self.assertEqual(analysis["mensaje"], "Resultado jurídico: Conformidad.")
        self.assertEqual(memory_ocr.call_args.args[2][0].contenido, b"contenido-seleccionado")
        self.assertEqual(classify.call_args.args[2][0].ubicacion_original, "escritura.docx")
        self.assertFalse((root / "Expedientes").exists())

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
            classification = ResultadoClasificacion(
                "EXP-WEB",
                (DocumentoClasificado(extracted.documento, None, None, "No identificado", (), "Sin evidencia."),),
                "Salida/EXP-WEB/clasificacion_documental.json",
            )
            trace_record = RegistroTrazabilidad(
                "MIN-001",
                extracted.documento,
                1,
                "MIN-CLA-001",
                "Texto diferente",
                "Texto esperado",
                "No coincide",
                "La cláusula difiere.",
            )
            legal_result = ResultadoMotorJuridico(
                "EXP-WEB",
                "No Conformidad",
                (),
                (),
                (),
                "Salida/EXP-WEB/resultado_juridico.json",
                ResumenMotorJuridico(0, 0, 0, 0, 0, 0, 0),
                "Concepto jurídico.",
                ResultadoTrazabilidad("Síntesis jurídica.", (trace_record,), (trace_record,)),
            )
            with (
                patch("Codigo.ocr._extract_document", return_value=[extracted]),
                patch("Codigo.web.classify_expediente_documents", return_value=classification),
                patch("Codigo.web.extract_expediente_data", return_value=ResultadoExtraccion("EXP-WEB", (), (), "Salida/EXP-WEB/extraccion_documental.json")),
                patch("Codigo.web.normalize_expediente_data", return_value=ResultadoNormalizacion("EXP-WEB", (), (), "Salida/EXP-WEB/normalizacion_documental.json", ResumenNormalizacion(0, 0, 0, ()))),
                patch("Codigo.web.validate_expediente_data", return_value=ResultadoValidaciones("EXP-WEB", (), "Salida/EXP-WEB/validaciones_documentales.json", ResumenValidacion(0, 0, 0, 0, 0, 0))),
                patch("Codigo.web.apply_legal_engine", return_value=legal_result),
            ):
                with urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            with urlopen(
                f"http://{address}:{port}/api/analisis/progreso?id_expediente=EXP-WEB"
            ) as response:
                progress = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(payload["mensaje"], "Resultado jurídico: No Conformidad.")
        self.assertEqual(payload["ocr"]["archivo_salida"], "Salida/EXP-WEB/texto_extraido.json")
        self.assertIn("Clasificación: Salida/EXP-WEB/clasificacion_documental.json", payload["detalle"])
        self.assertEqual(payload["clasificacion"]["archivo_salida"], "Salida/EXP-WEB/clasificacion_documental.json")
        self.assertEqual(payload["extraccion"]["archivo_salida"], "Salida/EXP-WEB/extraccion_documental.json")
        self.assertEqual(payload["normalizacion"]["archivo_salida"], "Salida/EXP-WEB/normalizacion_documental.json")
        self.assertEqual(payload["validacion"]["archivo_salida"], "Salida/EXP-WEB/validaciones_documentales.json")
        self.assertEqual(payload["motor_juridico"]["archivo_salida"], "Salida/EXP-WEB/resultado_juridico.json")
        self.assertEqual(payload["motor_juridico"]["resultado"], "No Conformidad")
        self.assertEqual(payload["trazabilidad"]["sintesis_dictamen"], "Síntesis jurídica.")
        self.assertIsInstance(payload["trazabilidad"]["inconsistencias"][0]["pagina"], int)
        self.assertEqual(payload["trazabilidad"]["inconsistencias"][0]["resultado"], "No coincide")
        output = json.loads((root / payload["ocr"]["archivo_salida"]).read_text(encoding="utf-8"))
        self.assertEqual(output["textos"][0]["documento"], extracted.documento)
        self.assertEqual(output["textos"][0]["pagina"], 1)
        self.assertEqual(output["textos"][0]["texto"], "texto visible")
        self.assertEqual(output["textos"][0]["metodo"], "OCR imagen")
        self.assertEqual(output["textos"][0]["confianza"], 95.0)
        self.assertEqual(progress["estado"], "completado")
        self.assertEqual(progress["archivo_salida"], "Salida/EXP-WEB/texto_extraido.json")
        self.assertEqual(progress["archivo_clasificacion"], "Salida/EXP-WEB/clasificacion_documental.json")
        self.assertEqual(progress["archivo_extraccion"], "Salida/EXP-WEB/extraccion_documental.json")
        self.assertEqual(progress["archivo_normalizacion"], "Salida/EXP-WEB/normalizacion_documental.json")
        self.assertEqual(progress["archivo_validaciones"], "Salida/EXP-WEB/validaciones_documentales.json")
        self.assertEqual(progress["archivo_resultado_juridico"], "Salida/EXP-WEB/resultado_juridico.json")
        self.assertEqual(progress["resultado_juridico"], "No Conformidad")
        self.assertEqual(progress["completadas"], 1)
        self.assertEqual(progress["total"], 1)

    def test_official_interface_contains_simple_accessible_progress_below_analysis_button(self) -> None:
        interface = (Path(__file__).parent.parent / "Programa" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="analysis-progress"', interface)
        self.assertIn('role="progressbar"', interface)
        self.assertIn('id="progress-percent"', interface)
        self.assertNotIn('id="expediente-select"', interface)
        self.assertIn('id="btn-select"', interface)
        self.assertIn('id="file-input"', interface)
        self.assertIn('aria-valuenow="0"', interface)
        self.assertLess(interface.index('id="btn-analyze"'), interface.index('id="analysis-progress"'))
        self.assertLess(
            interface.index('id="analysis-progress"'),
            interface.index('<section class="card results-section">'),
        )
        self.assertNotIn('id="progress-remaining"', interface)
        self.assertIn('Use “Seleccionar archivos”', interface)
        self.assertIn('El servidor local no está disponible.', interface)
        self.assertIn("fetch('/api/estado', {cache: 'no-store'})", interface)
        self.assertIn('recargue esta página', interface)
        self.assertIn('tamano_maximo_seleccion_mb', interface)
        self.assertIn('supera el límite configurado', interface)
        self.assertIn("analyzeButtonPreparingText = 'PREPARANDO ARCHIVOS'", interface)
        self.assertIn("analyzeButtonReadyText = 'INICIAR ANÁLISIS'", interface)
        self.assertIn('setAnalyzeButtonPreparing();', interface)
        self.assertNotIn('Preparando selección en memoria', interface)
        self.assertIn('id="validation-details"', interface)
        self.assertLess(interface.index("Validaciones realizadas:"), interface.index('id="output-info"'))
        self.assertIn("renderTraceability", interface)
        self.assertIn("sintesis_dictamen", interface)
        self.assertIn("Página", interface)
        self.assertIn("Valor esperado", interface)
        self.assertIn("Valor encontrado", interface)
        self.assertIn("Resultado", interface)
        self.assertIn("Coincide", interface)
        self.assertIn("No coincide", interface)
        self.assertNotIn("Diferencias frente a Minuta_hipoteca", interface)

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
