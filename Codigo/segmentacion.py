"""Segmentación lógica de documentos guiada por ``15_Segmentacion_Documental``.

La fase conserva el nombre y la paginación del archivo original. Su salida
añade un identificador lógico y un rol sugerido para que la clasificación no
confunda una referencia interna con el documento que realmente se analiza.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .clasificacion import _matches, _read_shared_strings, _read_sheet, _worksheet_paths
from .config import ConfigurationError, ProjectConfiguration, load_configuration


class SegmentationError(ValueError):
    """La arquitectura o el OCR no permiten construir documentos lógicos."""


@dataclass(frozen=True)
class ReglaSegmentacion:
    id_segmentacion: str
    id_perfil: str
    anclas_inicio: tuple[str, ...]
    anclas_fin: tuple[str, ...]
    senal_continuacion: str
    paginas_minimas: int
    permite_documento_compuesto: bool
    rol_sugerido: str
    control: str


@dataclass(frozen=True)
class DocumentoLogico:
    documento_logico_id: str
    documento_original: str
    pagina_inicio: int
    pagina_fin: int
    paginas: tuple[int, ...]
    id_perfil_sugerido: str | None
    rol_sugerido: str | None
    estado: str
    evidencia: str


@dataclass(frozen=True)
class ResultadoSegmentacion:
    id_expediente: str
    documentos_logicos: tuple[DocumentoLogico, ...]
    archivo_salida: str


def _parts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _rules(configuration: ProjectConfiguration) -> tuple[ReglaSegmentacion, ...]:
    try:
        sheet_name = str(configuration.values["hojas"]["segmentacion_documental"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            paths = _worksheet_paths(workbook)
            rows = _read_sheet(workbook, paths[sheet_name], _read_shared_strings(workbook))
    except KeyError:
        # Compatibilidad de lectura con arquitecturas anteriores; en la
        # arquitectura vigente la hoja es obligatoria y se valida al arranque.
        return ()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SegmentationError(f"No fue posible leer 15_Segmentacion_Documental: {error}") from error
    return tuple(
        ReglaSegmentacion(
            row.get("ID_Segmentacion", "").strip(),
            row.get("ID_Perfil", "").strip(),
            _parts(row.get("Ancla_Inicio", "")),
            _parts(row.get("Ancla_Fin", "")),
            row.get("Senal_Continuacion", "").strip(),
            max(1, int(float(row.get("Paginas_Minimas", "1") or 1))),
            row.get("Permite_Documento_Compuesto", "").strip().casefold() in {"si", "sí", "1", "true"},
            row.get("Rol_Sugerido", "").strip(),
            row.get("Control", "").strip(),
        )
        for row in rows
        if row.get("ID_Segmentacion", "").strip()
    )


def _load_ocr(configuration: ProjectConfiguration, expediente_id: str) -> list[dict[str, Any]]:
    filename = str(configuration.values.get("ocr", {}).get("archivo_salida", "texto_extraido.json"))
    path = configuration.route("salida") / expediente_id / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SegmentationError(f"No fue posible leer el resultado OCR: {error}") from error
    if payload.get("id_expediente") != expediente_id or not isinstance(payload.get("textos"), list):
        raise SegmentationError("El resultado OCR no corresponde al expediente seleccionado")
    return [item for item in payload["textos"] if isinstance(item, dict)]


def _best_rule(pages: list[dict[str, Any]], rules: tuple[ReglaSegmentacion, ...]) -> tuple[ReglaSegmentacion | None, str]:
    candidates: list[tuple[int, ReglaSegmentacion, str]] = []
    for rule in rules:
        matches: list[str] = []
        for page in pages[:3]:
            text = str(page.get("texto", ""))
            matches.extend(anchor for anchor in rule.anclas_inicio if _matches(anchor, text))
        if matches:
            candidates.append((max(len(item.split()) for item in matches), rule, max(matches, key=len)))
    if not candidates:
        return None, "Sin ancla inicial concluyente; se conserva el archivo como una unidad lógica."
    candidates.sort(key=lambda item: (item[0], item[1].paginas_minimas), reverse=True)
    _, rule, evidence = candidates[0]
    return rule, evidence


def _output_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    settings = configuration.values.get("segmentacion", {})
    filename = str(settings.get("archivo_salida", "segmentacion_documental.json")) if isinstance(settings, dict) else "segmentacion_documental.json"
    if Path(filename).name != filename:
        raise SegmentationError("El archivo de segmentación debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def segment_expediente_documents(
    project_root: Path,
    expediente_id: str,
    ocr_texts: tuple[Any, ...] | None = None,
) -> ResultadoSegmentacion:
    """Genera una unidad lógica por archivo y registra el perfil/rol sustentado."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise SegmentationError(str(error)) from error
    rules = _rules(configuration)
    raw_pages = (
        [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in ocr_texts]
        if ocr_texts is not None
        else _load_ocr(configuration, expediente_id)
    )
    by_document: dict[str, list[dict[str, Any]]] = {}
    for page in raw_pages:
        document = page.get("documento")
        if isinstance(document, str) and document:
            by_document.setdefault(document, []).append(page)
    logical_documents: list[DocumentoLogico] = []
    for index, (document, pages) in enumerate(by_document.items(), start=1):
        ordered = sorted(pages, key=lambda item: int(item.get("pagina", 0) or 0))
        numbers = tuple(int(item.get("pagina", 0) or 0) for item in ordered if int(item.get("pagina", 0) or 0) > 0)
        rule, evidence = _best_rule(ordered, rules)
        logical_documents.append(
            DocumentoLogico(
                f"LOG-{index:04d}",
                document,
                min(numbers) if numbers else 1,
                max(numbers) if numbers else 1,
                numbers or (1,),
                rule.id_perfil if rule else None,
                rule.rol_sugerido if rule else None,
                "Segmentado" if rule else "Revisión requerida",
                evidence,
            )
        )
    if not logical_documents:
        raise SegmentationError("El OCR no contiene páginas que puedan segmentarse")
    path = _output_path(configuration, expediente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = ResultadoSegmentacion(expediente_id, tuple(logical_documents), "")
    path.write_text(
        json.dumps(
            {"id_expediente": expediente_id, "documentos_logicos": [asdict(item) for item in logical_documents]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return ResultadoSegmentacion(
        expediente_id,
        tuple(logical_documents),
        path.relative_to(configuration.project_root).as_posix(),
    )
