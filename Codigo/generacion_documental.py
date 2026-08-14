"""Generación Word/PDF posterior a la confirmación humana.

Las plantillas oficiales se leen como fuente inmutable. El módulo reemplaza
únicamente los marcadores declarados en ``09_Marcadores_Documento`` y deja el
consecutivo sin intervención, de acuerdo con la regla DOC-002.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from lxml import etree as LxmlElementTree
except ImportError:  # pragma: no cover - validado por bootstrap/dependencias
    LxmlElementTree = None

from .clasificacion import _normalizar, _read_shared_strings, _read_sheet, _worksheet_paths
from .config import ConfigurationError, ProjectConfiguration, load_configuration
from .revision_analista import AnalystReviewError, authorize_document_generation


class DocumentGenerationError(ValueError):
    """La revisión, los datos o la plantilla no permiten generar el certificado."""


@dataclass(frozen=True)
class MarcadorDocumento:
    marcador: str
    id_campo: str
    origen_dato: str
    obligatorio: bool
    valor_defecto: str
    transformacion: str


@dataclass(frozen=True)
class ResultadoGeneracionDocumental:
    id_expediente: str
    resultado_confirmado: str
    plantilla: str
    hash_plantilla_antes: str
    hash_plantilla_despues: str
    archivo_word: str
    archivo_pdf: str
    marcadores_reemplazados: tuple[str, ...]
    consecutivo: str
    archivo_control: str


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML = "http://www.w3.org/XML/1998/namespace"
_MARKER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path, description: str, expediente_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DocumentGenerationError(f"No fue posible leer {description}: {error}") from error
    if not isinstance(payload, dict) or payload.get("id_expediente") != expediente_id:
        raise DocumentGenerationError(f"{description.capitalize()} no corresponde al expediente")
    return payload


def _filename(configuration: ProjectConfiguration, section: str, default: str) -> str:
    settings = configuration.values.get(section, {})
    value = str(settings.get("archivo_salida", default)) if isinstance(settings, dict) else default
    if Path(value).name != value:
        raise DocumentGenerationError(f"El archivo de {section} debe ser un nombre de archivo")
    return value


def _markers(configuration: ProjectConfiguration, document_key: str) -> tuple[MarcadorDocumento, ...]:
    try:
        sheet = str(configuration.values["hojas"]["marcadores"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            rows = _read_sheet(workbook, _worksheet_paths(workbook)[sheet], _read_shared_strings(workbook))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise DocumentGenerationError(f"No fue posible leer 09_Marcadores_Documento: {error}") from error
    return tuple(
        MarcadorDocumento(
            row.get("Marcador", "").strip(),
            row.get("ID_Campo", "").strip(),
            row.get("Origen_Dato", "").strip(),
            _normalizar(row.get("Obligatorio", "")) == "si",
            row.get("Valor_Defecto", "").strip(),
            row.get("Transformacion", "").strip(),
        )
        for row in rows
        if row.get("Documento", "").strip() == document_key and row.get("Marcador", "").strip()
    )


def _all_field_values(extraction: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}

    def add(field: dict[str, Any]) -> None:
        field_id = str(field.get("id_campo", ""))
        for item in field.get("valores", []) if isinstance(field.get("valores"), list) else []:
            if isinstance(item, dict) and item.get("valor_encontrado") is not None:
                result.setdefault(field_id, []).append(str(item["valor_encontrado"]))
            elif isinstance(item, str):
                result.setdefault(field_id, []).append(item)

    for field in extraction.get("campos", []):
        if not isinstance(field, dict):
            continue
        add(field)
        for obj in field.get("objetos", []) if isinstance(field.get("objetos"), list) else []:
            if isinstance(obj, dict):
                for child in obj.get("campos", []) if isinstance(obj.get("campos"), list) else []:
                    if isinstance(child, dict):
                        add(child)
    return {key: list(dict.fromkeys(value for value in values if value.strip())) for key, values in result.items()}


def _person_values(extraction: dict[str, Any]) -> dict[str, str]:
    preferred = {"hipotecante": 0, "comprador": 1, "deudor": 2, "afiliado": 3}
    candidates: list[tuple[int, dict[str, str]]] = []
    for field in extraction.get("campos", []):
        if not isinstance(field, dict) or str(field.get("id_campo")) != "PER-001":
            continue
        for obj in field.get("objetos", []):
            mapped: dict[str, str] = {}
            if not isinstance(obj, dict):
                continue
            for child in obj.get("campos", []):
                if not isinstance(child, dict):
                    continue
                values = child.get("valores", [])
                if isinstance(values, list) and values:
                    mapped[str(child.get("id_campo", ""))] = str(values[0])
            role = _normalizar(mapped.get("PER-005", ""))
            rank = min((value for key, value in preferred.items() if key in role), default=99)
            candidates.append((rank, mapped))
    return min(candidates, key=lambda item: item[0])[1] if candidates else {}


def _first(values: dict[str, list[str]], field_id: str, person: dict[str, str]) -> str:
    return person.get(field_id) or (values.get(field_id) or [""])[0]


def _currency(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"$ {int(digits):,}".replace(",", ".") if digits else value


def _reference(values: dict[str, list[str]], fields: tuple[str, str, str, str], label: str) -> str:
    number, when, notary, city = ((values.get(field) or [""])[0] for field in fields)
    parts = [f"{label} {number}".strip()]
    if when:
        parts.append(f"de fecha {when}")
    if notary:
        parts.append(f"otorgada en {notary}")
    if city:
        parts.append(f"de {city}")
    return " ".join(part for part in parts if part and part != label)


def _observations(legal: dict[str, Any]) -> str:
    trace = legal.get("trazabilidad", {})
    inconsistencies = trace.get("inconsistencias", []) if isinstance(trace, dict) else []
    lines = []
    for index, item in enumerate(inconsistencies if isinstance(inconsistencies, list) else [], 1):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"{index}. {item.get('campo') or item.get('id_regla')}: "
            f"{item.get('observacion') or 'Debe corregirse o aportarse evidencia suficiente.'}"
        )
    return "\n".join(lines) or "1. Completar la evidencia faltante indicada en el análisis jurídico confirmado."


def _marker_values(
    markers: tuple[MarcadorDocumento, ...],
    extraction: dict[str, Any],
    legal: dict[str, Any],
) -> dict[str, str]:
    values = _all_field_values(extraction)
    person = _person_values(extraction)
    today = date.today()
    generated: dict[str, str] = {}
    for marker in markers:
        if marker.marcador == "FECHA_CERTIFICADO":
            value = f"{today.day} de {_MONTHS[today.month - 1]} de {today.year}"
        elif marker.marcador == "REFERENCIA_ESCRITURA":
            value = _reference(values, ("ESC-003", "ESC-004", "ESC-005", "ESC-006"), "Escritura pública")
        elif marker.marcador == "PODER_REFERENCIA":
            value = _reference(values, ("POD-007", "POD-005", "POD-009", "POD-010"), "Poder")
        elif marker.marcador == "OBSERVACIONES_NO_CONFORMIDAD":
            value = _observations(legal)
        elif marker.marcador == "MATRICULAS":
            value = ", ".join(values.get(marker.id_campo, []))
        else:
            value = _first(values, marker.id_campo, person)
        if _normalizar(marker.transformacion) == "formato moneda":
            value = _currency(value)
        if not value:
            value = marker.valor_defecto or ("NO INFORMADO" if marker.obligatorio else "No aplica")
        generated[marker.marcador] = value
    return generated


def _replace_in_xml(content: bytes, replacements: dict[str, str]) -> bytes:
    if LxmlElementTree is None:
        raise DocumentGenerationError("Falta la dependencia lxml para preservar el formato Word oficial")
    parser = LxmlElementTree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = LxmlElementTree.fromstring(content, parser)
    for paragraph in root.iter(f"{{{_W}}}p"):
        texts = list(paragraph.iter(f"{{{_W}}}t"))
        if not texts:
            continue
        combined = "".join(item.text or "" for item in texts)
        replaced = combined
        for marker, value in replacements.items():
            replaced = replaced.replace("{{" + marker + "}}", value)
        if replaced == combined:
            continue
        runs = list(paragraph.iter(f"{{{_W}}}r"))
        if not runs:
            continue
        for run in runs:
            for child in list(run):
                if child.tag in {f"{{{_W}}}t", f"{{{_W}}}br"}:
                    run.remove(child)
        first_run = runs[0]
        for index, segment in enumerate(replaced.split("\n")):
            if index:
                LxmlElementTree.SubElement(first_run, f"{{{_W}}}br")
            text_node = LxmlElementTree.SubElement(first_run, f"{{{_W}}}t")
            text_node.set(f"{{{_XML}}}space", "preserve")
            text_node.text = segment
    return LxmlElementTree.tostring(root, encoding="utf-8", xml_declaration=True, standalone=True)


def _create_word(template: Path, output: Path, replacements: dict[str, str]) -> tuple[str, ...]:
    output.parent.mkdir(parents=True, exist_ok=True)
    replaced_files: list[str] = []
    try:
        with zipfile.ZipFile(template) as source, zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    updated = _replace_in_xml(content, replacements)
                    if updated != content:
                        replaced_files.append(info.filename)
                    content = updated
                target.writestr(info, content)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise DocumentGenerationError(f"No fue posible generar el Word oficial: {error}") from error
    with zipfile.ZipFile(output) as generated:
        visible = "\n".join(
            "".join(ElementTree.fromstring(generated.read(name)).itertext())
            for name in generated.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        )
    pending = sorted(set(_MARKER.findall(visible)))
    if pending:
        raise DocumentGenerationError("El Word conserva marcadores sin reemplazar: " + ", ".join(pending))
    return tuple(sorted(replacements))


def _convert_pdf(configuration: ProjectConfiguration, word: Path, pdf: Path) -> None:
    settings = configuration.values.get("generacion_documental", {})
    command = str(settings.get("comando_libreoffice", "soffice")) if isinstance(settings, dict) else "soffice"
    executable = shutil.which(command)
    if executable:
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent), str(word)],
            capture_output=True,
            text=True,
        )
        converted = pdf.parent / f"{word.stem}.pdf"
        if result.returncode == 0 and converted.is_file():
            if converted != pdf:
                converted.replace(pdf)
            return
    word_literal = str(word.resolve()).replace("'", "''")
    pdf_literal = str(pdf.resolve()).replace("'", "''")
    script = (
        "$app=New-Object -ComObject Word.Application; $app.Visible=$false; "
        f"try {{$doc=$app.Documents.Open('{word_literal}',$false,$true); "
        f"$doc.SaveAs2('{pdf_literal}',17); $doc.Close()}} "
        "finally {if ($null -ne $app) {$app.Quit()}}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DocumentGenerationError(f"No fue posible iniciar la conversión PDF: {error}") from error
    if result.returncode != 0 or not pdf.is_file():
        detail = (result.stderr or result.stdout).strip()
        raise DocumentGenerationError(f"No fue posible convertir el certificado a PDF: {detail or 'convertidor no disponible'}")


def generate_official_document(project_root: Path, expediente_id: str) -> ResultadoGeneracionDocumental:
    """Genera los dos formatos después de verificar la confirmación del analista."""
    try:
        configuration = load_configuration(project_root)
        authorization = authorize_document_generation(project_root, expediente_id)
    except (ConfigurationError, AnalystReviewError) as error:
        raise DocumentGenerationError(str(error)) from error
    template = configuration.project_root / authorization.plantilla
    template_key = "Certificado_Conformidad" if authorization.resultado_confirmado == "Conformidad" else "Certificado_No_Conformidad"
    marker_definitions = _markers(configuration, template_key)
    if any(item.marcador == "CONSECUTIVO" for item in marker_definitions):
        raise DocumentGenerationError("DOC-002 impide que el consecutivo sea un marcador automático")
    output = configuration.route("salida") / expediente_id
    extraction = _load_json(output / _filename(configuration, "extraccion", "extraccion_documental.json"), "la extracción", expediente_id)
    legal = _load_json(output / _filename(configuration, "motor_juridico", "resultado_juridico.json"), "el resultado jurídico", expediente_id)
    replacements = _marker_values(marker_definitions, extraction, legal)
    settings = configuration.values.get("generacion_documental", {})
    pattern_key = "nombre_word_conformidad" if authorization.resultado_confirmado == "Conformidad" else "nombre_word_no_conformidad"
    pattern = str(settings.get(pattern_key, f"{template_key}_{{id_expediente}}.docx")) if isinstance(settings, dict) else f"{template_key}_{{id_expediente}}.docx"
    word = output / pattern.format(id_expediente=expediente_id)
    pdf = word.with_suffix(".pdf")
    before = _hash(template)
    replaced = _create_word(template, word, replacements)
    after = _hash(template)
    if before != after:
        raise DocumentGenerationError("La plantilla oficial fue alterada durante la generación")
    _convert_pdf(configuration, word, pdf)
    control_name = str(settings.get("archivo_control", "generacion_documental.json")) if isinstance(settings, dict) else "generacion_documental.json"
    control = output / control_name
    provisional = ResultadoGeneracionDocumental(
        expediente_id,
        authorization.resultado_confirmado,
        authorization.plantilla,
        before,
        after,
        word.relative_to(configuration.project_root).as_posix(),
        pdf.relative_to(configuration.project_root).as_posix(),
        replaced,
        "Diligenciamiento manual exclusivo del analista (DOC-002)",
        control.relative_to(configuration.project_root).as_posix(),
    )
    control.write_text(json.dumps(asdict(provisional), ensure_ascii=False, indent=2), encoding="utf-8")
    return provisional
