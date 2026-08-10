"""Pruebas del motor de extracción documental GIOJ-006."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Codigo.extraccion import ExtractionError, extract_expediente_data


FIELD_HEADER = [
    "ID_Campo", "Nivel", "Campo_Padre", "Entidad", "Campo",
    "Descripción", "Tipo_Dato", "Catalogo_Asociado", "Múltiples",
    "Obligatorio", "Observaciones", "Mostrar_Resultado",
]
INSTRUCTION_HEADER = [
    "ID_Extraccion", "ID_Campo", "Prioridad", "Documento_Origen",
    "Regla_Extraccion", "Regla_Validacion", "Permite_OCR",
    "Puede_Heredarse", "Campo_Destino", "Observaciones",
]


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


def _write_architecture(root: Path, sheets: dict[str, list[list[str]]] | None = None) -> None:
    sheets = sheets or {
        "01_Campos_Extraccion": [
            FIELD_HEADER,
            ["PER-001", "Entidad", "", "Persona", "Intervinientes", "Personas", "Lista_Objeto", "", "Sí", "Sí", "", ""],
            ["PER-002", "Atributo", "Intervinientes", "Persona", "Nombre", "Nombre completo", "Texto", "", "No", "Sí", "", "Si"],
            ["ESC-001", "Entidad", "", "Escritura", "Escrituras", "Escrituras", "Lista_Objeto", "", "Sí", "Sí", "", ""],
            ["ESC-004", "Atributo", "Escrituras", "Escritura", "Fecha", "Fecha", "Fecha", "", "No", "Sí", "", "Si"],
        ],
        "05_Extraccion_Documental": [
            INSTRUCTION_HEADER,
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


def create_project(sheets: dict[str, list[list[str]]] | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "Arquitectura").mkdir()
    (root / "Arquitectura" / "config.json").write_text(json.dumps({
        "rutas": {"arquitectura": "./Arquitectura/Arquitectura.xlsx", "logs": "./Logs/", "salida": "./Salida/"},
        "hojas": {"campos": "01_Campos_Extraccion", "extraccion": "05_Extraccion_Documental"},
        "ocr": {"archivo_salida": "texto_extraido.json"},
        "extraccion": {"archivo_salida": "campos.json"},
    }), encoding="utf-8")
    _write_architecture(root, sheets)
    return root


def _write_analysis_inputs(
    root: Path,
    expediente_id: str,
    pages: list[dict[str, object]],
    documents: list[dict[str, object]],
) -> None:
    output = root / "Salida" / expediente_id
    output.mkdir(parents=True)
    (output / "texto_extraido.json").write_text(
        json.dumps(
            {"id_expediente": expediente_id, "textos": pages},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output / "clasificacion_documental.json").write_text(
        json.dumps(
            {"id_expediente": expediente_id, "documentos": documents},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class ExtractionTests(unittest.TestCase):
    def test_extracts_only_configured_fields_and_keeps_page_evidence(self) -> None:
        root = create_project()
        document = "Expedientes/EXP-001/01_Documentos/cedula.pdf"
        _write_analysis_inputs(
            root,
            "EXP-001",
            [{
                "documento": document,
                "pagina": 2,
                "texto": "Nombre: ANA PEREZ",
                "metodo": "OCR",
                "confianza": 92.5,
            }],
            [{
                "documento": document,
                "tipo_documental": "Documento de Identidad",
                "codigo_tipo_documental": "DOC_ID",
            }],
        )

        result = extract_expediente_data(root, "EXP-001")

        self.assertEqual(result.archivo_salida, "Salida/EXP-001/campos.json")
        expected_ids = ["PER-001", "PER-002", "ESC-001", "ESC-004"]
        self.assertEqual(
            [item.campo.id_campo for item in result.campos],
            expected_ids,
        )
        nombre = next(item for item in result.campos if item.campo.id_campo == "PER-002")
        self.assertEqual(nombre.estado, "Extraído")
        self.assertEqual(nombre.valores[0].valor_encontrado, "ANA PEREZ")
        self.assertEqual(nombre.valores[0].pagina, 2)
        self.assertEqual(nombre.valores[0].documento, document)
        self.assertEqual(nombre.valores[0].confianza, 92.5)
        intervinientes = next(
            item for item in result.campos
            if item.campo.id_campo == "PER-001"
        )
        self.assertEqual(intervinientes.estado, "Extraído")
        self.assertEqual(len(intervinientes.objetos), 1)
        self.assertEqual(intervinientes.objetos[0].documentos, (document,))
        self.assertEqual(intervinientes.objetos[0].paginas, (2,))
        self.assertEqual(
            [field.id_campo for field in intervinientes.objetos[0].campos],
            ["PER-002"],
        )
        self.assertEqual(
            intervinientes.objetos[0].campos[0].valores,
            ("ANA PEREZ",),
        )
        self.assertEqual(
            intervinientes.objetos[0].campos[0].evidencias[0].pagina,
            2,
        )
        self.assertIsNotNone(result.resumen)
        self.assertEqual(result.resumen.total_campos_definidos, 4)
        self.assertEqual(result.resumen.total_campos_salida, 4)
        self.assertEqual(result.resumen.campos_con_informacion, 2)
        self.assertEqual(result.resumen.campos_sin_informacion, 2)
        self.assertEqual(result.resumen.total_valores_extraidos, 1)
        self.assertEqual(result.resumen.total_evidencias_extraidas, 1)
        self.assertEqual(result.resumen.total_objetos_extraidos, 1)
        self.assertEqual(result.resumen.campos_obligatorios, 4)
        self.assertEqual(result.resumen.obligatorios_con_informacion, 2)
        self.assertEqual(
            result.resumen.obligatorios_sin_informacion,
            ("ESC-001", "ESC-004"),
        )
        self.assertTrue(result.resumen.esquema_completo)
        self.assertFalse(result.resumen.cumple_campos_obligatorios)
        self.assertEqual(len(result.advertencias_configuracion), 1)
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(
            [item["id_campo"] for item in saved["campos"]],
            expected_ids,
        )
        self.assertEqual(saved["resumen"]["total_campos_definidos"], 4)
        self.assertTrue(saved["resumen"]["esquema_completo"])
        self.assertEqual(
            saved["datos_estructurados"]["Intervinientes"],
            saved["campos"][0]["objetos"],
        )
        self.assertEqual(saved["datos_estructurados"]["Escrituras"], [])
        self.assertIn("INEXISTENTE-001", saved["advertencias_configuracion"][0])
        self.assertIn("EXTRACCION COMPLETADA", (root / "Logs" / "extraccion.log").read_text(encoding="utf-8"))

    def test_extracts_a_dynamic_architecture_with_28_ordered_fields(self) -> None:
        field_rows = [FIELD_HEADER]
        instruction_rows = [INSTRUCTION_HEADER]
        expected_ids: list[str] = []
        pages: list[dict[str, object]] = []
        documents: list[dict[str, object]] = []
        expected_children: dict[str, list[str]] = {}

        for entity_number in range(1, 8):
            collection = f"Coleccion{entity_number:02d}"
            entity = f"Entidad{entity_number:02d}"
            entity_id = f"ENT-{entity_number:03d}"
            source = f"Fuente{entity_number:02d}"
            document = (
                "Expedientes/EXP-028/01_Documentos/"
                f"fuente-{entity_number:02d}.pdf"
            )
            field_rows.append([
                entity_id, "Entidad", "", entity, collection,
                f"Colección sintética {entity_number}", "Lista_Objeto", "",
                "Sí", "Sí", "", "Sí",
            ])
            instruction_rows.append([
                f"EXT-E-{entity_number:03d}", entity_id, "1", "Contexto",
                f"Agrupar {collection}.", "", "No", "No", collection, "",
            ])
            expected_ids.append(entity_id)
            expected_children[entity_id] = []
            page_lines: list[str] = []

            for attribute_number in range(1, 4):
                field_id = f"ATR-{entity_number:02d}-{attribute_number:02d}"
                field_name = f"Dato{entity_number:02d}{attribute_number:02d}"
                value = f"VALOR{entity_number:02d}{attribute_number:02d}"
                field_rows.append([
                    field_id, "Atributo", collection, entity, field_name,
                    field_name, "Texto", "", "No", "Sí", "", "Sí",
                ])
                instruction_rows.append([
                    f"EXT-A-{entity_number:02d}-{attribute_number:02d}",
                    field_id, "1", source, f"Extraer {field_name}.", "",
                    "Sí", "No", f"{collection}[].{field_name}", "",
                ])
                expected_ids.append(field_id)
                expected_children[entity_id].append(field_id)
                page_lines.append(f"{field_name}: {value}")

            pages.append({
                "documento": document,
                "pagina": 1,
                "texto": "\n".join(page_lines),
                "metodo": "PDF digital",
                "confianza": None,
            })
            documents.append({
                "documento": document,
                "tipo_documental": source,
                "codigo_tipo_documental": source,
            })

        root = create_project({
            "01_Campos_Extraccion": field_rows,
            "05_Extraccion_Documental": instruction_rows,
        })
        _write_analysis_inputs(root, "EXP-028", pages, documents)

        result = extract_expediente_data(root, "EXP-028")

        self.assertEqual(len(expected_ids), 28)
        self.assertEqual(
            [item.campo.id_campo for item in result.campos],
            expected_ids,
        )
        self.assertIsNotNone(result.resumen)
        self.assertEqual(result.resumen.total_campos_definidos, 28)
        self.assertEqual(result.resumen.total_campos_salida, 28)
        self.assertEqual(result.resumen.campos_con_informacion, 28)
        self.assertEqual(result.resumen.campos_sin_informacion, 0)
        self.assertEqual(result.resumen.total_valores_extraidos, 21)
        self.assertEqual(result.resumen.total_evidencias_extraidas, 21)
        self.assertEqual(result.resumen.total_objetos_extraidos, 7)
        self.assertEqual(result.resumen.campos_obligatorios, 28)
        self.assertEqual(result.resumen.obligatorios_con_informacion, 28)
        self.assertEqual(result.resumen.obligatorios_sin_informacion, ())
        self.assertTrue(result.resumen.esquema_completo)
        self.assertTrue(result.resumen.cumple_campos_obligatorios)
        for entity_id, child_ids in expected_children.items():
            entity_result = next(
                item for item in result.campos
                if item.campo.id_campo == entity_id
            )
            self.assertEqual(len(entity_result.objetos), 1)
            self.assertEqual(
                [field.id_campo for field in entity_result.objetos[0].campos],
                child_ids,
            )
        saved = json.loads((root / result.archivo_salida).read_text(encoding="utf-8"))
        self.assertEqual(
            [item["id_campo"] for item in saved["campos"]],
            expected_ids,
        )
        self.assertEqual(len(saved["datos_estructurados"]), 7)

    def test_wrong_source_does_not_create_a_value_even_when_inheritable(self) -> None:
        sheets = {
            "01_Campos_Extraccion": [
                FIELD_HEADER,
                ["ENT-001", "Entidad", "", "Entidad", "Coleccion", "Colección", "Lista_Objeto", "", "Sí", "Sí", "", "Sí"],
                ["ATR-001", "Atributo", "Coleccion", "Entidad", "Secreto", "Secreto", "Texto", "", "No", "Sí", "", "Sí"],
            ],
            "05_Extraccion_Documental": [
                INSTRUCTION_HEADER,
                ["EXT-001", "ENT-001", "1", "Contexto", "Agrupar Coleccion.", "", "No", "No", "Coleccion", ""],
                ["EXT-002", "ATR-001", "1", "Fuente_Correcta", "Extraer Secreto.", "", "Sí", "Sí", "Coleccion[].Secreto", ""],
            ],
        }
        root = create_project(sheets)
        document = "Expedientes/EXP-SOURCE/01_Documentos/fuente-incorrecta.pdf"
        _write_analysis_inputs(
            root,
            "EXP-SOURCE",
            [{
                "documento": document,
                "pagina": 1,
                "texto": "Secreto: NO DEBE EXTRAERSE",
                "metodo": "PDF digital",
                "confianza": None,
            }],
            [{
                "documento": document,
                "tipo_documental": "Fuente Incorrecta",
                "codigo_tipo_documental": "FUENTE_INCORRECTA",
            }],
        )

        result = extract_expediente_data(root, "EXP-SOURCE")

        field = next(item for item in result.campos if item.campo.id_campo == "ATR-001")
        entity = next(item for item in result.campos if item.campo.id_campo == "ENT-001")
        self.assertEqual(field.estado, "No existe información")
        self.assertEqual(field.valores, ())
        self.assertEqual(entity.objetos, ())
        self.assertEqual(
            result.resumen.obligatorios_sin_informacion,
            ("ENT-001", "ATR-001"),
        )

    def test_permite_ocr_is_applied_per_page(self) -> None:
        sheets = {
            "01_Campos_Extraccion": [
                FIELD_HEADER,
                ["ENT-001", "Entidad", "", "Entidad", "Coleccion", "Colección", "Lista_Objeto", "", "Sí", "Sí", "", "Sí"],
                ["ATR-YES", "Atributo", "Coleccion", "Entidad", "Permitido", "Permitido", "Texto", "", "No", "Sí", "", "Sí"],
                ["ATR-NO", "Atributo", "Coleccion", "Entidad", "Bloqueado", "Bloqueado", "Texto", "", "No", "Sí", "", "Sí"],
            ],
            "05_Extraccion_Documental": [
                INSTRUCTION_HEADER,
                ["EXT-ENT", "ENT-001", "1", "Contexto", "Agrupar Coleccion.", "", "No", "No", "Coleccion", ""],
                ["EXT-YES", "ATR-YES", "1", "Fuente_Prueba", "Extraer Permitido.", "", "Sí", "No", "Coleccion[].Permitido", ""],
                ["EXT-NO", "ATR-NO", "1", "Fuente_Prueba", "Extraer Bloqueado.", "", "No", "No", "Coleccion[].Bloqueado", ""],
            ],
        }
        root = create_project(sheets)
        document = "Expedientes/EXP-OCR/01_Documentos/fuente.pdf"
        _write_analysis_inputs(
            root,
            "EXP-OCR",
            [
                {
                    "documento": document,
                    "pagina": 1,
                    "texto": (
                        "Permitido: VALOR OCR\n"
                        "Bloqueado: PROHIBIDO OCR"
                    ),
                    "metodo": "OCR PDF escaneado",
                    "confianza": 88.0,
                },
                {
                    "documento": document,
                    "pagina": 2,
                    "texto": "Bloqueado: VALOR DIGITAL",
                    "metodo": "PDF digital",
                    "confianza": None,
                },
            ],
            [{
                "documento": document,
                "tipo_documental": "Fuente Prueba",
                "codigo_tipo_documental": "FUENTE_PRUEBA",
            }],
        )

        result = extract_expediente_data(root, "EXP-OCR")

        allowed = next(item for item in result.campos if item.campo.id_campo == "ATR-YES")
        blocked = next(item for item in result.campos if item.campo.id_campo == "ATR-NO")
        self.assertEqual(
            {item.valor_encontrado for item in allowed.valores},
            {"VALOR OCR"},
        )
        self.assertEqual({item.pagina for item in allowed.valores}, {1})
        self.assertEqual(
            {item.valor_encontrado for item in blocked.valores},
            {"VALOR DIGITAL"},
        )
        self.assertEqual({item.pagina for item in blocked.valores}, {2})
        self.assertTrue(all("ocr" in item.metodo.lower() for item in allowed.valores))
        self.assertTrue(all(item.metodo == "PDF digital" for item in blocked.valores))

    def test_rejects_duplicate_field_id_and_unknown_parent(self) -> None:
        invalid_architectures = {
            "ID_Campo duplicados": {
                "01_Campos_Extraccion": [
                    FIELD_HEADER,
                    ["DUP-001", "Entidad", "", "Entidad", "Coleccion", "Colección", "Lista_Objeto", "", "Sí", "Sí", "", "Sí"],
                    ["DUP-001", "Atributo", "Coleccion", "Entidad", "Dato", "Dato", "Texto", "", "No", "Sí", "", "Sí"],
                ],
                "05_Extraccion_Documental": [
                    INSTRUCTION_HEADER,
                    ["EXT-001", "DUP-001", "1", "Fuente", "Extraer Dato.", "", "Sí", "No", "Coleccion[].Dato", ""],
                ],
            },
            "Campo_Padre": {
                "01_Campos_Extraccion": [
                    FIELD_HEADER,
                    ["ENT-001", "Entidad", "", "Entidad", "Coleccion", "Colección", "Lista_Objeto", "", "Sí", "Sí", "", "Sí"],
                    ["ATR-001", "Atributo", "NoExiste", "Entidad", "Dato", "Dato", "Texto", "", "No", "Sí", "", "Sí"],
                ],
                "05_Extraccion_Documental": [
                    INSTRUCTION_HEADER,
                    ["EXT-001", "ATR-001", "1", "Fuente", "Extraer Dato.", "", "Sí", "No", "Coleccion[].Dato", ""],
                ],
            },
        }
        for expected_message, sheets in invalid_architectures.items():
            with self.subTest(expected_message=expected_message):
                root = create_project(sheets)
                with self.assertRaisesRegex(ExtractionError, expected_message):
                    extract_expediente_data(root, "EXP-INVALID")


if __name__ == "__main__":
    unittest.main()
