"""Motor de extracción documental definido por ``Arquitectura.xlsx``.

Esta fase no contiene campos jurídicos codificados. Lee exclusivamente las
hojas ``01_Campos_Extraccion`` y ``05_Extraccion_Documental`` para construir
las instrucciones que se aplican al texto OCR y a su clasificación previa.
Cada valor conserva la evidencia que permite a las fases posteriores ubicarlo
en el documento original.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .clasificacion import _normalizar, _read_shared_strings, _read_sheet, _worksheet_paths
from .config import ConfigurationError, ProjectConfiguration, load_configuration


class ExtractionError(ValueError):
    """Indica una entrada o arquitectura no apta para la extracción."""


@dataclass(frozen=True)
class CampoExtraccion:
    """Campo oficial de la hoja ``01_Campos_Extraccion``."""

    id_campo: str
    nivel: str
    campo_padre: str | None
    entidad: str
    campo: str
    descripcion: str | None
    tipo_dato: str | None
    catalogo_asociado: str | None
    multiples: str | None
    obligatorio: str | None
    observaciones: str | None
    mostrar_resultado: str | None


@dataclass(frozen=True)
class InstruccionExtraccion:
    """Instrucción oficial de la hoja ``05_Extraccion_Documental``."""

    id_extraccion: str
    id_campo: str
    prioridad: str | None
    documento_origen: str
    regla_extraccion: str | None
    regla_validacion: str | None
    permite_ocr: str | None
    puede_heredarse: str | None
    campo_destino: str | None
    observaciones: str | None


@dataclass(frozen=True)
class EvidenciaExtraccion:
    """Valor y ubicación exacta recuperados del resultado OCR."""

    valor_encontrado: str
    documento: str
    pagina: int
    metodo: str | None
    confianza: float | None
    evidencia_textual: str
    id_extraccion: str | None = None
    documento_origen: str | None = None
    prioridad: float | None = None
    heredado: bool = False
    calidad: int | None = None


@dataclass(frozen=True)
class CampoObjeto:
    """Valores de un atributo dentro de una entidad consolidada."""

    id_campo: str
    campo: str
    valores: tuple[str, ...]
    evidencias: tuple[EvidenciaExtraccion, ...] = ()


@dataclass(frozen=True)
class ObjetoExtraido:
    """Consolidación documental de una entidad definida en la arquitectura."""

    documento: str
    paginas: tuple[int, ...]
    campos: tuple[CampoObjeto, ...]
    documentos: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoCampo:
    """Resultado de aplicar las instrucciones disponibles para un campo."""

    campo: CampoExtraccion
    estado: str
    instrucciones: tuple[str, ...]
    valores: tuple[EvidenciaExtraccion, ...]
    observacion: str | None
    objetos: tuple[ObjetoExtraido, ...] = ()


@dataclass(frozen=True)
class ResumenExtraccion:
    """Controles de cobertura del esquema y de campos obligatorios."""

    total_campos_definidos: int
    total_campos_salida: int
    campos_con_informacion: int
    campos_sin_informacion: int
    total_valores_extraidos: int
    total_evidencias_extraidas: int
    total_objetos_extraidos: int
    campos_obligatorios: int
    obligatorios_con_informacion: int
    obligatorios_sin_informacion: tuple[str, ...]
    esquema_completo: bool
    cumple_campos_obligatorios: bool


@dataclass(frozen=True)
class ResultadoExtraccion:
    """Salida estructurada y persistida del motor de extracción."""

    id_expediente: str
    campos: tuple[ResultadoCampo, ...]
    advertencias_configuracion: tuple[str, ...]
    archivo_salida: str
    resumen: ResumenExtraccion | None = None


_ACTION_WORDS = frozenset({
    "a", "al", "asignar", "comparar", "contra", "con", "de", "del", "desde",
    "detectar", "determinar", "el", "en", "extraer", "la", "las", "los", "por",
    "segun", "su", "sus", "un", "una", "validar", "verificar",
})
_GENERIC_WORDS = frozenset({
    "asociado", "asociada", "campo", "completa", "completo", "dato", "datos",
    "documental", "documento", "encontrado", "expediente", "informacion", "principal",
    "registrada", "registrado", "relacionado", "relacionada", "todos", "todas",
})
_LABEL_SEPARATOR = re.compile(
    r"\s*(?:[:#]|\bn(?:u\s*mero|úmero)\.?\s*:?"
    r"|\bno\.?\s*(?=[(\d])|n[°º]\.?)\s*",
    flags=re.IGNORECASE,
)
_VALUE_END = re.compile(r"\s{2,}|\n", flags=re.MULTILINE)
_MONEY_PATTERN = re.compile(r"\$\s?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\$\s?\d+(?:,\d+)?")
_DATE_PATTERN = re.compile(
    r"\b\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+de\s+\d{4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-](?:\d{2,4}|\d[.]\d{3})\b",
    flags=re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(
    r"(?<!\w)\d{1,4}(?:[.,-]\d{2,})+(?:-\d)?(?!\w)|(?<!\w)\d{3,}(?!\w)"
)


@dataclass(frozen=True)
class _Candidate:
    """Candidato interno antes de aplicar calidad, prioridad y deduplicación."""

    valor: str
    evidencia: str
    puntaje: int


def _value(row: dict[str, str], name: str) -> str | None:
    value = row.get(name, "").strip()
    return value or None


def _read_extraction_architecture(configuration: ProjectConfiguration) -> tuple[tuple[CampoExtraccion, ...], tuple[InstruccionExtraccion, ...]]:
    """Carga solo las dos hojas autorizadas para esta etapa."""
    try:
        names = configuration.values["hojas"]
        fields_name = str(names["campos"])
        extraction_name = str(names["extraccion"])
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            shared_strings = _read_shared_strings(workbook)
            paths = _worksheet_paths(workbook)
            field_rows = _read_sheet(workbook, paths[fields_name], shared_strings)
            extraction_rows = _read_sheet(workbook, paths[extraction_name], shared_strings)
    except (KeyError, OSError, zipfile.BadZipFile, ValueError) as error:
        raise ExtractionError(f"No fue posible leer las hojas de extracción autorizadas: {error}") from error
    fields = tuple(
        CampoExtraccion(
            id_campo=row["ID_Campo"].strip(),
            nivel=_value(row, "Nivel") or "",
            campo_padre=_value(row, "Campo_Padre"),
            entidad=_value(row, "Entidad") or "",
            campo=_value(row, "Campo") or "",
            descripcion=_value(row, "Descripción"),
            tipo_dato=_value(row, "Tipo_Dato"),
            catalogo_asociado=_value(row, "Catalogo_Asociado"),
            multiples=_value(row, "Múltiples"),
            obligatorio=_value(row, "Obligatorio"),
            observaciones=_value(row, "Observaciones"),
            mostrar_resultado=_value(row, "Mostrar_Resultado"),
        )
        for row in field_rows
        if _value(row, "ID_Campo")
    )
    instructions = tuple(
        InstruccionExtraccion(
            id_extraccion=row["ID_Extraccion"].strip(),
            id_campo=_value(row, "ID_Campo") or "",
            prioridad=_value(row, "Prioridad"),
            documento_origen=_value(row, "Documento_Origen") or "",
            regla_extraccion=_value(row, "Regla_Extraccion"),
            regla_validacion=_value(row, "Regla_Validacion"),
            permite_ocr=_value(row, "Permite_OCR"),
            puede_heredarse=_value(row, "Puede_Heredarse"),
            campo_destino=_value(row, "Campo_Destino"),
            observaciones=_value(row, "Observaciones"),
        )
        for row in extraction_rows
        if _value(row, "ID_Extraccion")
    )
    if not fields:
        raise ExtractionError("01_Campos_Extraccion no contiene campos definidos")
    if not instructions:
        raise ExtractionError("05_Extraccion_Documental no contiene instrucciones definidas")
    _validate_extraction_architecture(fields, instructions)
    return fields, instructions


def load_extraction_fields(configuration: ProjectConfiguration) -> tuple[CampoExtraccion, ...]:
    """Expone los campos oficiales ya validados de ``01_Campos_Extraccion``."""
    fields, _instructions = _read_extraction_architecture(configuration)
    return fields


def _read_extraction_catalogs(
    configuration: ProjectConfiguration,
) -> dict[str, tuple[str, ...]]:
    """Carga valores activos de 03_Catalogos sin duplicarlos en código."""
    sheet_name = configuration.values.get("hojas", {}).get("catalogos")
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        return {}
    try:
        with zipfile.ZipFile(configuration.route("arquitectura")) as workbook:
            rows = _read_sheet(
                workbook,
                _worksheet_paths(workbook)[sheet_name],
                _read_shared_strings(workbook),
            )
    except (KeyError, OSError, zipfile.BadZipFile, ValueError) as error:
        raise ExtractionError(f"No fue posible leer 03_Catalogos: {error}") from error
    values: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        catalog = _value(row, "Catalogo")
        value = _value(row, "Valor")
        active = _normalizar(_value(row, "Activo") or "1")
        if catalog and value and active not in {"0", "false", "no"}:
            values[catalog].append(value)
    return {
        catalog: tuple(dict.fromkeys(items))
        for catalog, items in values.items()
    }


def _validate_extraction_architecture(
    fields: tuple[CampoExtraccion, ...],
    instructions: tuple[InstruccionExtraccion, ...],
) -> None:
    """Valida unicidad y relaciones sin completar definiciones por código."""
    field_ids = [field.id_campo for field in fields]
    duplicate_fields = tuple(
        field_id for field_id in dict.fromkeys(field_ids)
        if field_ids.count(field_id) > 1
    )
    if duplicate_fields:
        raise ExtractionError(
            "01_Campos_Extraccion contiene ID_Campo duplicados: "
            + ", ".join(duplicate_fields)
        )
    instruction_ids = [item.id_extraccion for item in instructions]
    duplicate_instructions = tuple(
        instruction_id for instruction_id in dict.fromkeys(instruction_ids)
        if instruction_ids.count(instruction_id) > 1
    )
    if duplicate_instructions:
        raise ExtractionError(
            "05_Extraccion_Documental contiene ID_Extraccion duplicados: "
            + ", ".join(duplicate_instructions)
        )

    entities: dict[str, list[CampoExtraccion]] = defaultdict(list)
    for field in fields:
        level = _normalizar(field.nivel)
        if level not in {"entidad", "atributo"}:
            raise ExtractionError(
                f"{field.id_campo}: Nivel desconocido: {field.nivel or '(vacío)'}"
            )
        if level == "entidad":
            entities[_normalizar(field.campo)].append(field)
    for field in fields:
        if _normalizar(field.nivel) != "atributo":
            continue
        matches = entities.get(_normalizar(field.campo_padre or ""), [])
        if len(matches) != 1:
            raise ExtractionError(
                f"{field.id_campo}: Campo_Padre {field.campo_padre or '(vacío)'} "
                "no identifica una única entidad de 01_Campos_Extraccion"
            )


def _load_json(path: Path, subject: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExtractionError(f"No se encontró {subject}; ejecute primero la fase anterior")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExtractionError(f"No fue posible leer {subject}: {error}") from error
    if not isinstance(payload, dict):
        raise ExtractionError(f"{subject} tiene un formato inválido")
    return payload


def _ocr_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    filename = str(configuration.values.get("ocr", {}).get("archivo_salida", "texto_extraido.json"))
    if Path(filename).name != filename:
        raise ExtractionError("El archivo de salida OCR debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _classification_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    return configuration.route("salida") / expediente_id / "clasificacion_documental.json"


def _output_path(configuration: ProjectConfiguration, expediente_id: str) -> Path:
    settings = configuration.values.get("extraccion", {})
    filename = str(settings.get("archivo_salida", "extraccion_documental.json")) if isinstance(settings, dict) else "extraccion_documental.json"
    if Path(filename).name != filename:
        raise ExtractionError("El archivo de salida de extracción debe ser un nombre de archivo")
    return configuration.route("salida") / expediente_id / filename


def _is_true(value: str | None) -> bool:
    return _normalizar(value or "") in {"1", "si", "s", "true"}


def _priority(value: str | None) -> float:
    try:
        return float(value or 999)
    except ValueError:
        return 999.0


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        word
        for word in _normalizar(value.replace("[]", " ").replace("_", " ")).split()
        if word not in _ACTION_WORDS and word not in _GENERIC_WORDS
    )


def _instruction_phrases(
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
) -> tuple[str, ...]:
    """Compila etiquetas estrictas desde Campo, Destino y Regla_Extraccion."""
    phrases: list[str] = []
    for value in (
        field.campo,
        _destination_name(instruction.campo_destino),
        field.descripcion or "",
    ):
        words = _content_tokens(value)
        if words:
            phrases.append(" ".join(words))

    rule = instruction.regla_extraccion or ""
    rule = re.split(
        r"\b(?:desde|según|contra|usando|mediante)\b",
        rule,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    rule_words = _content_tokens(rule)
    if rule_words:
        phrases.append(" ".join(rule_words))
        if len(rule_words) == 2:
            phrases.append(" ".join(reversed(rule_words)))

    field_words = _content_tokens(field.campo)
    if (
        len(field_words) == 1
        and len(rule_words) > 1
        and field_words[0] in rule_words
    ):
        phrases = [
            phrase for phrase in phrases
            if phrase != field_words[0]
        ]

    return tuple(dict.fromkeys(sorted(
        (phrase for phrase in phrases if len(phrase) >= 3),
        key=lambda item: (-len(item.split()), -len(item)),
    )))


def _destination_name(destination: str | None) -> str:
    """Obtiene el último segmento del destino sin modificar la definición oficial."""
    if not destination:
        return ""
    return destination.replace("[]", "").split(".")[-1].strip()


def _normalized_with_map(value: str) -> tuple[str, tuple[int, ...]]:
    """Normaliza una línea conservando el índice que corresponde al texto original."""
    normalized: list[str] = []
    positions: list[int] = []
    previous_space = True
    for index, character in enumerate(value):
        decomposed = re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFD", character.casefold()))
        for item in decomposed:
            if item.isalnum() or item == "_":
                normalized.append(item)
                positions.append(index)
                previous_space = False
            elif not previous_space:
                normalized.append(" ")
                positions.append(index)
                previous_space = True
    while normalized and normalized[-1] == " ":
        normalized.pop()
        positions.pop()
    return "".join(normalized), tuple(positions)


def _clean_value(value: str) -> str:
    cleaned = _VALUE_END.split(value)[0].strip(" \t.:;,#-_()[]{}")
    cleaned = re.sub(r"^(?:es|son|denominad[oa]s?|corresponde\s+a)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:no\.?|n[°ºo]?\.?)\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .;,-")


def _phrase_pattern(phrase: str) -> str:
    """Tolera conectores y marcas de plural sin perder límites de palabra."""
    words = phrase.split()
    if not words:
        return r"(?!)"
    connector = r"(?:\s+(?:s|de|del|la|el|los|las))*\s+"
    components = [
        r"(?:numero|no|n)"
        if word == "numero"
        else re.escape(word) + (r"(?:s|es)?" if len(word) > 3 else "")
        for word in words
    ]
    return r"(?<!\w)" + connector.join(components) + r"(?!\w)"


def _label_value(value: str, field: CampoExtraccion) -> tuple[str, ...]:
    """Valida el fragmento posterior a una etiqueta según el tipo declarado."""
    kind = _normalizar(field.tipo_dato or "")
    if kind == "fecha":
        numeric_dates = tuple(match.group(0).strip() for match in _DATE_PATTERN.finditer(value))
        if numeric_dates:
            return numeric_dates
        textual_date = re.search(
            r"([^\n]*\(\d{1,2}\)[\s\S]{0,140}?\bde\b[\s\S]{0,140}?\(\d{4}\))",
            value,
            flags=re.IGNORECASE,
        )
        return (" ".join(textual_date.group(1).split()),) if textual_date else ()
    if kind == "moneda":
        return tuple(match.group(0).strip() for match in _MONEY_PATTERN.finditer(value))
    value = re.sub(r"^\s*[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,24}\s*:\s*", "", value)
    cleaned = _clean_value(value)
    return (cleaned,) if _valid_candidate(cleaned, field) else ()


def _valid_candidate(value: str, field: CampoExtraccion) -> bool:
    normalized = _normalizar(value)
    if not normalized or len(normalized) < 2 or len(value) > 260:
        return False
    if normalized in {"s", "es", "as", "no", "n", _normalizar(field.campo)}:
        return False
    if re.fullmatch(r"[_xX\s()./-]+", value):
        return False
    return "favor completar" not in normalized and "xxxx" not in normalized


def _labelled_candidates(text: str, phrases: tuple[str, ...], field: CampoExtraccion) -> tuple[_Candidate, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[_Candidate] = []
    for line_index in range(len(lines)):
        for width in range(1, min(3, len(lines) - line_index) + 1):
            segment = "\n".join(lines[line_index:line_index + width])
            normalized_segment, positions = _normalized_with_map(segment)
            for phrase in phrases:
                match = re.search(_phrase_pattern(phrase), normalized_segment)
                if match is None or not positions:
                    continue
                prefix = normalized_segment[:match.start()].strip()
                at_start = not prefix or (
                    len(prefix.split()) == 1
                    and bool(re.fullmatch(r"(?:[ivxlcdm]+|\d+)", prefix))
                )
                original_end = positions[min(match.end() - 1, len(positions) - 1)] + 1
                remainder = segment[original_end:]
                remainder = re.sub(r"^\s*(?:\(\s*s\s*\)|s\b)\s*", "", remainder, flags=re.IGNORECASE)
                separator = _LABEL_SEPARATOR.match(remainder)
                if separator is None and at_start:
                    separator = re.match(
                        r"^\s+(?:(?:[^\W\d_]+|\d+)\s+){0,6}"
                        r"[:#]\s*",
                        remainder,
                        flags=re.IGNORECASE,
                    )
                label_on_own_line = separator is None and remainder.startswith("\n")
                if separator is None and not label_on_own_line:
                    continue
                if separator:
                    remainder = remainder[separator.end():]
                elif label_on_own_line:
                    remainder = remainder.lstrip()
                remainder = remainder.lstrip()
                first_letter = next((character for character in remainder if character.isalpha()), "")
                if separator is None and first_letter and first_letter.islower():
                    continue
                for value in _label_value(remainder, field):
                    if not _valid_candidate(value, field):
                        continue
                    score = 45 + 8 * len(phrase.split())
                    field_phrase = " ".join(_content_tokens(field.campo))
                    if phrase == field_phrase:
                        score += 60
                    elif (
                        field_phrase
                        and set(field_phrase.split()).issubset(set(phrase.split()))
                        and len(phrase.split()) > len(field_phrase.split())
                    ):
                        score += 40
                    if separator:
                        score += 12
                    if at_start:
                        score += 8
                    candidates.append(_Candidate(value, segment, score))
                break
    return tuple(candidates)


def _example_values(
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
    catalog_values: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values: list[str] = list(catalog_values)
    for source in (field.descripcion or "", field.observaciones or "", instruction.observaciones or ""):
        match = re.search(r"\bejemplos?\s*:\s*(.+)", source, flags=re.IGNORECASE)
        if not match:
            continue
        example = re.sub(r"\betc\.?$", "", match.group(1).strip(), flags=re.IGNORECASE)
        values.extend(part.strip(" .") for part in re.split(r"\s*[,;]\s*|\s+o\s+|\s+y\s+", example) if part.strip(" ."))
    rule = instruction.regla_extraccion or ""
    if _normalizar(rule).startswith("asignar"):
        remaining = re.sub(r"^\s*asignar\s+", "", rule, flags=re.IGNORECASE)
        field_terms = set(_content_tokens(field.campo))
        words = remaining.strip(" .").split()
        while words and _normalizar(words[0]) in field_terms:
            words.pop(0)
        if words:
            values.append(" ".join(words).strip(" ."))
    return tuple(dict.fromkeys(value for value in values if value))


def _assigned_value(
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
) -> str | None:
    """Interpreta una asignación literal declarada en Regla_Extraccion."""
    rule = instruction.regla_extraccion or ""
    if not _normalizar(rule).startswith("asignar"):
        return None
    remaining = re.sub(
        r"^\s*asignar\s+", "", rule, flags=re.IGNORECASE
    ).strip(" .;")
    field_terms = tuple(_content_tokens(field.campo))
    words = remaining.split()
    while words and field_terms and _normalizar(words[0]) in field_terms:
        words.pop(0)
    value = " ".join(words).strip(" .;")
    return value or None


def _enumerated_candidates(
    text: str,
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
    catalog_values: tuple[str, ...] = (),
) -> tuple[_Candidate, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[_Candidate] = []
    for option in _example_values(field, instruction, catalog_values):
        normalized_option = _normalizar(option)
        for line in lines:
            normalized_line = _normalizar(line)
            found = re.search(rf"(?<!\w){re.escape(normalized_option)}(?!\w)", normalized_line)
            if len(normalized_option) <= 4:
                letters = [re.escape(character) for character in option if character.isalnum()]
                found_original = re.search(
                    r"(?<![\w.])" + r"[\W_]*".join(letters) + r"\.?(?![\w.])",
                    line,
                    flags=re.IGNORECASE,
                )
                if (found or found_original) and _NUMBER_PATTERN.search(line):
                    candidates.append(_Candidate(option, line, 120))
                continue
            if found:
                candidates.append(_Candidate(option, line, 120))
    return tuple(candidates)


def _edit_distance(first: str, second: str) -> int:
    """Distancia acotada para tolerar etiquetas deformadas por OCR."""
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, 1):
        current = [row]
        for column, right in enumerate(second, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def _fuzzy_label_candidates(
    text: str,
    phrases: tuple[str, ...],
    field: CampoExtraccion,
) -> tuple[_Candidate, ...]:
    """Recupera un valor tras una etiqueta corta con hasta dos errores OCR."""
    candidates: list[_Candidate] = []
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        label = _normalizar(parts[0])
        for phrase in phrases:
            if " " in phrase or len(phrase) < 5:
                continue
            if _edit_distance(label, phrase) > 2:
                continue
            values = _label_value(parts[1], field)
            for value in values:
                normalized_number = re.fullmatch(r"[\d.,\s-]{5,}", value)
                cleaned = re.sub(r"\D", "", value) if normalized_number else value
                if _valid_candidate(cleaned, field):
                    candidates.append(_Candidate(cleaned, line, 128))
            break
    return tuple(candidates)


def _preceding_label_candidates(
    text: str,
    phrases: tuple[str, ...],
    field: CampoExtraccion,
) -> tuple[_Candidate, ...]:
    """Admite documentos cuyo rótulo se imprime debajo del valor."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[_Candidate] = []
    complete_value = "completo" in _normalizar(field.descripcion or "")
    for index, label in enumerate(lines):
        normalized_label = _normalizar(label)
        if not any(re.fullmatch(_phrase_pattern(phrase), normalized_label) for phrase in phrases):
            continue
        preceding = lines[max(0, index - 3):index]
        textual = [
            value
            for value in preceding
            if not any(character.isdigit() for character in value)
            and 2 <= len(_normalizar(value).split()) <= 6
            and _valid_candidate(value, field)
        ]
        if not textual:
            continue
        selected = (
            [textual[-1], *textual[:-1]]
            if complete_value and len(textual) > 1
            else textual if complete_value else textual[-1:]
        )
        value = " ".join(selected)
        evidence = "\n".join([*preceding, label])
        candidates.append(_Candidate(value, evidence, 145 if complete_value else 132))
    return tuple(candidates)


def _anchor_score(context: str, terms: set[str]) -> int:
    context_terms = set(_normalizar(context).split())
    return 10 * len(context_terms & terms)


def _typed_candidates(
    text: str,
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
    related_labels: tuple[str, ...],
    catalog_values: tuple[str, ...] = (),
) -> tuple[_Candidate, ...]:
    """Aplica patrones genéricos compilados desde las hojas 01 y 05."""
    phrases = _instruction_phrases(field, instruction)
    kind = _normalizar(field.tipo_dato or "")
    enum_options = (
        _example_values(field, instruction, catalog_values)
        if kind == "enumerado"
        else ()
    )
    candidates = []
    for candidate in _labelled_candidates(text, phrases, field):
        value = candidate.valor
        normalized_value = _normalizar(value)
        matching_options = [
            option for option in enum_options
            if re.search(
                rf"(?<!\w){re.escape(_normalizar(option))}(?!\w)",
                normalized_value,
            )
        ]
        if matching_options:
            value = max(matching_options, key=len)
        normalized_evidence = _normalizar(candidate.evidencia)
        sibling_matches = sum(
            1 for label in related_labels
            if re.search(_phrase_pattern(_normalizar(label)), normalized_evidence)
        )
        candidates.append(_Candidate(
            value,
            candidate.evidencia,
            candidate.puntaje + min(sibling_matches, 3) * 8,
        ))
    candidates.extend(_fuzzy_label_candidates(text, phrases, field))
    candidates.extend(_preceding_label_candidates(text, phrases, field))
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if kind == "enumerado":
        candidates.extend(_enumerated_candidates(
            text, field, instruction, catalog_values
        ))

    if kind == "enumerado":
        denomination = re.compile(
            r"\bdenominad[oa]s?\b\s*[:\-]?\s*"
            r"(?:\(([^)]+)\)|([^.;]{3,120}))",
            flags=re.IGNORECASE,
        )
        semantic_terms = {
            word
            for phrase in phrases
            for word in phrase.split()
        }
        for index, line in enumerate(lines):
            context = " ".join(lines[index : min(len(lines), index + 3)])
            if (
                semantic_terms
                and not semantic_terms & set(_normalizar(context).split())
            ):
                continue
            for match in denomination.finditer(context):
                value = _clean_value(match.group(1) or match.group(2) or "")
                if _valid_candidate(value, field):
                    candidates.append(_Candidate(value, context, 95))

    return tuple(candidates)


def _select_candidates(candidates: tuple[_Candidate, ...], field: CampoExtraccion) -> tuple[_Candidate, ...]:
    valid = [candidate for candidate in candidates if _valid_candidate(candidate.valor, field)]
    if not valid:
        return ()
    best_by_value: dict[str, _Candidate] = {}
    for candidate in valid:
        key = _normalizar(candidate.valor)
        if key not in best_by_value or candidate.puntaje > best_by_value[key].puntaje:
            best_by_value[key] = candidate
    values = list(best_by_value.values())
    kind = _normalizar(field.tipo_dato or "")
    best_score = max(item.puntaje for item in values)
    tolerance = 15 if kind == "enumerado" else 5 if kind in {"fecha", "moneda", "lista_objeto"} else 12
    values = [item for item in values if item.puntaje >= best_score - tolerance]
    return tuple(sorted(values, key=lambda item: (-item.puntaje, _normalizar(item.valor)))[:40])


def _extract_values(
    field: CampoExtraccion,
    instruction: InstruccionExtraccion,
    pages: list[dict[str, Any]],
    related_labels: tuple[str, ...] = (),
    inherited: bool = False,
    catalog_values: tuple[str, ...] = (),
) -> tuple[EvidenciaExtraccion, ...]:
    """Extrae sin descartar líneas repetidas y respeta Permite_OCR por página."""
    values: list[EvidenciaExtraccion] = []
    assigned = _assigned_value(field, instruction)
    line_counts: dict[str, int] = defaultdict(int)
    for source_page in pages:
        for line in str(source_page.get("texto") or "").splitlines():
            normalized_line = _normalizar(line)
            if normalized_line:
                line_counts[normalized_line] += 1
    for page in pages:
        text = page.get("texto")
        if not isinstance(text, str) or not text.strip():
            continue
        method = page.get("metodo")
        is_ocr_page = (
            isinstance(method, str)
            and "ocr" in _normalizar(method)
        )
        if is_ocr_page and not _is_true(instruction.permite_ocr):
            continue
        if assigned:
            confidence = page.get("confianza")
            return (EvidenciaExtraccion(
                valor_encontrado=assigned,
                documento=str(page.get("documento", "")),
                pagina=int(page.get("pagina", 0) or 0),
                metodo=method if isinstance(method, str) else None,
                confianza=(
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    else None
                ),
                evidencia_textual=(
                    instruction.regla_extraccion or assigned
                ),
                id_extraccion=instruction.id_extraccion,
                documento_origen=instruction.documento_origen,
                prioridad=_priority(instruction.prioridad),
                heredado=inherited,
                calidad=100,
            ),)
        raw_candidates = _typed_candidates(
            text, field, instruction, related_labels, catalog_values
        )
        adjusted_candidates = tuple(
            _Candidate(
                candidate.valor,
                candidate.evidencia,
                candidate.puntaje - (
                    60
                    if line_counts[
                        _normalizar(
                            candidate.evidencia.splitlines()[0]
                        )
                    ] >= 3
                    else 0
                ),
            )
            for candidate in raw_candidates
        )
        adjusted_candidates = tuple(
            candidate for candidate in adjusted_candidates
            if candidate.puntaje >= 80
        )
        selected = _select_candidates(adjusted_candidates, field)
        for candidate in selected:
            confidence = page.get("confianza")
            values.append(EvidenciaExtraccion(
                valor_encontrado=candidate.valor,
                documento=str(page.get("documento", "")),
                pagina=int(page.get("pagina", 0) or 0),
                metodo=method if isinstance(method, str) else None,
                confianza=(
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    else None
                ),
                evidencia_textual=candidate.evidencia,
                id_extraccion=instruction.id_extraccion,
                documento_origen=instruction.documento_origen,
                prioridad=_priority(instruction.prioridad),
                heredado=inherited,
                calidad=candidate.puntaje,
            ))
    unique: dict[
        tuple[str, str, int, str, str | None],
        EvidenciaExtraccion,
    ] = {}
    for item in values:
        key = (
            _normalizar(item.valor_encontrado),
            item.documento,
            item.pagina,
            item.evidencia_textual,
            item.id_extraccion,
        )
        previous = unique.get(key)
        if previous is None or (item.calidad or 0) > (previous.calidad or 0):
            unique[key] = item
    return tuple(unique.values())


def _source_match_kind(
    instruction: InstruccionExtraccion,
    document: dict[str, Any],
    pages: list[dict[str, Any]],
) -> str | None:
    """Compara la fuente declarada con clasificación o estructura textual."""
    source = _normalizar(instruction.documento_origen.replace("_", " "))
    if source in {"contexto", "reglas negocio"}:
        return None
    source_terms = tuple(dict.fromkeys(_content_tokens(source)))
    if not source_terms:
        return None

    for candidate in (
        document.get("codigo_tipo_documental"),
        document.get("tipo_documental"),
    ):
        if not isinstance(candidate, str):
            continue
        candidate_terms = set(
            _content_tokens(candidate.replace("_", " "))
        )
        source_set = set(source_terms)
        if candidate_terms and (
            source_set <= candidate_terms
            or candidate_terms <= source_set
        ):
            return "exacto"

    page_lines = [
        [
            _normalizar(line)
            for line in str(page.get("texto") or "").splitlines()
            if line.strip()
        ]
        for page in sorted(
            pages, key=lambda item: int(item.get("pagina") or 0)
        )
    ]
    lines = [line for group in page_lines for line in group]
    joined = " ".join(lines)
    counts = {
        term: len(re.findall(_phrase_pattern(term), joined))
        for term in source_terms
    }
    if len(source_terms) == 1:
        term = source_terms[0]
        heading = any(
            line == term or line.startswith(term + " ")
            for line in lines
        )
        if heading or counts[term] >= 3:
            return "estructural"
    else:
        first_region = " ".join(
            line
            for group in page_lines[:2]
            for line in group[:40]
        )
        last_region = " ".join(
            line for group in page_lines[-3:] for line in group
        )
        first_anchor = re.search(
            _phrase_pattern(source_terms[0]),
            first_region,
        )
        last_anchor = re.search(
            _phrase_pattern(source_terms[-1]),
            last_region,
        )
        if (
            first_anchor
            and last_anchor
            and all(counts[term] for term in source_terms)
            and sum(counts.values()) >= len(source_terms) + 1
        ):
            return "estructural"
    return None


def _structural_source_pages(
    instruction: InstruccionExtraccion,
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Acota fuentes de una palabra a páginas con su ancla estructural."""
    terms = tuple(dict.fromkeys(_content_tokens(
        instruction.documento_origen.replace("_", " ")
    )))
    if len(terms) != 1:
        return pages
    term = terms[0]
    selected: list[dict[str, Any]] = []
    for page in pages:
        lines = [
            _normalizar(line)
            for line in str(page.get("texto") or "").splitlines()
            if line.strip()
        ]
        occurrences = sum(
            len(re.findall(_phrase_pattern(term), line))
            for line in lines
        )
        if (
            any(line == term or line.startswith(term + " ") for line in lines)
            or occurrences >= 2
        ):
            selected.append(page)
    return selected


def _field_related_labels(
    field: CampoExtraccion,
    fields: tuple[CampoExtraccion, ...],
    instructions_by_field: dict[str, tuple[InstruccionExtraccion, ...]],
) -> tuple[str, ...]:
    """Obtiene etiquetas de atributos hermanos sin conocer sus nombres."""
    labels: list[str] = []
    parent = _normalizar(field.campo_padre or "")
    for sibling in fields:
        if (
            sibling.id_campo == field.id_campo
            or _normalizar(sibling.campo_padre or "") != parent
        ):
            continue
        sibling_instructions = instructions_by_field.get(
            sibling.id_campo, ()
        )
        if sibling_instructions:
            for instruction in sibling_instructions:
                labels.extend(_instruction_phrases(
                    sibling, instruction
                ))
        else:
            labels.extend(_content_tokens(sibling.campo))
    return tuple(dict.fromkeys(labels))


def _evidence_tokens(evidence: EvidenciaExtraccion) -> set[str]:
    return set(_normalizar(
        f"{evidence.valor_encontrado} {evidence.evidencia_textual}"
    ).split())


def _cluster_anchor_values(
    cluster: dict[str, Any],
    child_by_id: dict[str, ResultadoCampo],
) -> set[tuple[str, str]]:
    anchors: set[tuple[str, str]] = set()
    for child_id, evidences in cluster["fields"].items():
        child = child_by_id[child_id]
        if _normalizar(child.campo.tipo_dato or "") == "enumerado":
            continue
        for evidence in evidences:
            value = _normalizar(evidence.valor_encontrado)
            if len(value) >= 4:
                anchors.add((child_id, value))
    return anchors


def _consolidate_entity(
    field: CampoExtraccion,
    child_results: tuple[ResultadoCampo, ...],
    instructions: tuple[InstruccionExtraccion, ...],
) -> ResultadoCampo:
    """Forma instancias por evidencia local y las une por valores compartidos."""
    child_by_id = {item.campo.id_campo: item for item in child_results}
    grouped: dict[
        tuple[str, int],
        list[tuple[ResultadoCampo, EvidenciaExtraccion]],
    ] = defaultdict(list)
    for child in child_results:
        for evidence in child.valores:
            grouped[(evidence.documento, evidence.pagina)].append(
                (child, evidence)
            )

    clusters: list[dict[str, Any]] = []
    for (document, page), items in grouped.items():
        distinct_by_field: dict[str, set[str]] = defaultdict(set)
        for child, evidence in items:
            distinct_by_field[child.campo.id_campo].add(
                _normalizar(evidence.valor_encontrado)
            )
        seed_id = max(
            distinct_by_field,
            key=lambda child_id: (
                len(distinct_by_field[child_id]),
                sum(
                    1 for child, _evidence in items
                    if child.campo.id_campo == child_id
                ),
            ),
        )
        page_clusters: list[dict[str, Any]] = []
        remaining: list[tuple[ResultadoCampo, EvidenciaExtraccion]] = []
        seen_seeds: set[str] = set()
        for child, evidence in items:
            normalized_value = _normalizar(evidence.valor_encontrado)
            if child.campo.id_campo == seed_id and normalized_value not in seen_seeds:
                seen_seeds.add(normalized_value)
                page_clusters.append({
                    "documents": {document},
                    "pages": {page},
                    "fields": defaultdict(
                        list, {seed_id: [evidence]}
                    ),
                    "tokens": _evidence_tokens(evidence),
                })
            else:
                remaining.append((child, evidence))

        for child, evidence in remaining:
            child_id = child.campo.id_campo
            evidence_tokens = _evidence_tokens(evidence)
            choices: list[tuple[float, dict[str, Any]]] = []
            for cluster in page_clusters:
                existing = cluster["fields"].get(child_id, [])
                conflicts = any(
                    _normalizar(item.valor_encontrado)
                    != _normalizar(evidence.valor_encontrado)
                    for item in existing
                )
                if conflicts:
                    continue
                union = cluster["tokens"] | evidence_tokens
                similarity = (
                    len(cluster["tokens"] & evidence_tokens) / len(union)
                    if union
                    else 0.0
                )
                choices.append((similarity, cluster))
            if choices:
                score, target = max(choices, key=lambda item: item[0])
            else:
                score, target = 0.0, None
            if target is None or (len(page_clusters) > 1 and score == 0):
                target = {
                    "documents": {document},
                    "pages": {page},
                    "fields": defaultdict(list),
                    "tokens": set(),
                }
                page_clusters.append(target)
            target["fields"][child_id].append(evidence)
            target["tokens"].update(evidence_tokens)
        clusters.extend(page_clusters)

    merged: list[dict[str, Any]] = []
    for cluster in clusters:
        anchors = _cluster_anchor_values(cluster, child_by_id)
        target = next(
            (
                candidate
                for candidate in merged
                if anchors
                and anchors
                & _cluster_anchor_values(candidate, child_by_id)
            ),
            None,
        )
        if target is None:
            merged.append(cluster)
            continue
        target["documents"].update(cluster["documents"])
        target["pages"].update(cluster["pages"])
        target["tokens"].update(cluster["tokens"])
        for child_id, evidences in cluster["fields"].items():
            target["fields"][child_id].extend(evidences)

    anchored = [
        cluster for cluster in merged
        if _cluster_anchor_values(cluster, child_by_id)
    ]
    for cluster in merged:
        if _cluster_anchor_values(cluster, child_by_id):
            continue
        candidates = [
            target for target in anchored
            if target["documents"] & cluster["documents"]
        ]
        if not candidates:
            continue
        target = max(
            candidates,
            key=lambda item: len(item["tokens"] & cluster["tokens"]),
        )
        target["documents"].update(cluster["documents"])
        target["pages"].update(cluster["pages"])
        target["tokens"].update(cluster["tokens"])
        for child_id, evidences in cluster["fields"].items():
            target["fields"][child_id].extend(evidences)
    merged = anchored

    objects: list[ObjetoExtraido] = []
    for cluster in merged:
        object_fields: list[CampoObjeto] = []
        for child in child_results:
            evidences = tuple(cluster["fields"].get(child.campo.id_campo, []))
            if not evidences:
                continue
            values = tuple(dict.fromkeys(
                item.valor_encontrado for item in evidences
            ))
            object_fields.append(CampoObjeto(
                child.campo.id_campo,
                child.campo.campo,
                values,
                evidences,
            ))
        if object_fields:
            documents = tuple(sorted(cluster["documents"]))
            objects.append(ObjetoExtraido(
                documents[0],
                tuple(sorted(cluster["pages"])),
                tuple(object_fields),
                documents,
            ))

    instruction_ids = tuple(item.id_extraccion for item in instructions)
    if objects:
        return ResultadoCampo(
            field,
            "Extraído",
            instruction_ids,
            (),
            "Entidad consolidada desde sus atributos según Campo_Padre.",
            tuple(objects),
        )
    return ResultadoCampo(
        field,
        "No existe información",
        instruction_ids,
        (),
        "No se encontraron atributos con evidencia para consolidar la entidad.",
    )


def _build_summary(fields: tuple[CampoExtraccion, ...], results: tuple[ResultadoCampo, ...]) -> ResumenExtraccion:
    with_information = tuple(item for item in results if item.valores or item.objetos)
    mandatory_ids = tuple(
        field.id_campo for field in fields
        if _is_true(field.obligatorio)
    )
    mandatory_with_information = {
        item.campo.id_campo for item in with_information
        if item.campo.id_campo in mandatory_ids
    }
    mandatory_missing = tuple(
        field_id for field_id in mandatory_ids
        if field_id not in mandatory_with_information
    )
    output_ids = tuple(item.campo.id_campo for item in results)
    field_ids = tuple(field.id_campo for field in fields)
    return ResumenExtraccion(
        total_campos_definidos=len(fields),
        total_campos_salida=len(results),
        campos_con_informacion=len(with_information),
        campos_sin_informacion=len(results) - len(with_information),
        total_valores_extraidos=sum(
            len({
                _normalizar(value.valor_encontrado)
                for value in item.valores
            })
            for item in results
        ),
        total_evidencias_extraidas=sum(
            len(item.valores) for item in results
        ),
        total_objetos_extraidos=sum(
            len(item.objetos) for item in results
        ),
        campos_obligatorios=len(mandatory_ids),
        obligatorios_con_informacion=len(mandatory_with_information),
        obligatorios_sin_informacion=mandatory_missing,
        esquema_completo=output_ids == field_ids,
        cumple_campos_obligatorios=not mandatory_missing,
    )


def _extraction_logger(log_directory: Path) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.extraccion.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "extraccion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _write_result(configuration: ProjectConfiguration, result: ResultadoExtraccion) -> Path:
    target = _output_path(configuration, result.id_expediente)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve().relative_to(configuration.route("salida").resolve())
    except ValueError as error:
        raise ExtractionError("El archivo de extracción sale de la ruta de salida configurada") from error
    payload = {
        "id_expediente": result.id_expediente,
        "campos": [
            {
                **asdict(item.campo),
                "estado": item.estado,
                "instrucciones": list(item.instrucciones),
                "valores": [asdict(value) for value in item.valores],
                "objetos": [asdict(value) for value in item.objetos],
                "observacion": item.observacion,
            }
            for item in result.campos
        ],
        "datos_estructurados": {
            item.campo.campo: [asdict(value) for value in item.objetos]
            for item in result.campos
            if _normalizar(item.campo.nivel) == "entidad"
        },
        "resumen": asdict(result.resumen) if result.resumen else None,
        "advertencias_configuracion": list(result.advertencias_configuracion),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def extract_expediente_data(project_root: Path, expediente_id: str) -> ResultadoExtraccion:
    """Extrae todos los campos configurados y persiste sus evidencias por página."""
    try:
        configuration = load_configuration(project_root)
    except ConfigurationError as error:
        raise ExtractionError(str(error)) from error
    fields, instructions = _read_extraction_architecture(configuration)
    catalogs = _read_extraction_catalogs(configuration)
    ocr = _load_json(_ocr_path(configuration, expediente_id), "el resultado OCR")
    classification = _load_json(_classification_path(configuration, expediente_id), "la clasificación documental")
    if ocr.get("id_expediente") != expediente_id or classification.get("id_expediente") != expediente_id:
        raise ExtractionError("Los resultados previos no corresponden al expediente seleccionado")
    pages = [item for item in ocr.get("textos", []) if isinstance(item, dict)]
    documents = [item for item in classification.get("documentos", []) if isinstance(item, dict)]
    field_ids = {field.id_campo for field in fields}
    fields_by_id = {field.id_campo: field for field in fields}
    warnings_list = [
        f"{instruction.id_extraccion}: ID_Campo {instruction.id_campo} no existe en 01_Campos_Extraccion."
        for instruction in instructions
        if instruction.id_campo not in field_ids
    ]
    warnings_list.extend(
        f"{instruction.id_extraccion}: Campo_Destino {instruction.campo_destino} no coincide con el campo {field.campo} de {field.id_campo}."
        for instruction in instructions
        for field in (fields_by_id.get(instruction.id_campo),)
        if field is not None
        and _destination_name(instruction.campo_destino)
        and _normalizar(_destination_name(instruction.campo_destino)) != _normalizar(field.campo)
    )
    warnings = tuple(warnings_list)
    pages_by_document: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        document = page.get("documento")
        if isinstance(document, str):
            pages_by_document.setdefault(document, []).append(page)
    instructions_by_field = {
        field.id_campo: tuple(sorted(
            (item for item in instructions if item.id_campo == field.id_campo),
            key=lambda item: (_priority(item.prioridad), item.id_extraccion),
        ))
        for field in fields
    }
    results_by_id: dict[str, ResultadoCampo] = {}
    attribute_fields = tuple(
        field
        for field in fields
        if _normalizar(field.nivel) == "atributo"
    )
    for field in attribute_fields:
        field_instructions = instructions_by_field[field.id_campo]
        evidences: list[EvidenciaExtraccion] = []
        applicable = 0
        related_labels = _field_related_labels(
            field, fields, instructions_by_field
        )
        for instruction in field_instructions:
            source = _normalizar(
                instruction.documento_origen.replace("_", " ")
            )
            if source in {"contexto", "reglas negocio"}:
                continue
            action = _normalizar(
                instruction.regla_extraccion or ""
            ).split()[:1]
            if not action or action[0] not in {
                "extraer", "detectar", "asignar",
            }:
                continue
            if (
                "no se extrae del expediente"
                in _normalizar(instruction.observaciones or "")
            ):
                continue
            matched: list[
                tuple[dict[str, Any], list[dict[str, Any]], str]
            ] = []
            for document in documents:
                source_pages = pages_by_document.get(
                    str(document.get("documento", "")), []
                )
                match_kind = _source_match_kind(
                    instruction, document, source_pages
                )
                if match_kind is not None:
                    matched.append(
                        (document, source_pages, match_kind)
                    )
            exact = [item for item in matched if item[2] == "exacto"]
            selected_documents = exact or matched
            inherited = False

            if (
                not selected_documents
                and _is_true(instruction.puede_heredarse)
            ):
                inherited_sources = tuple(dict.fromkeys(
                    sibling_instruction.documento_origen
                    for sibling in fields
                    if (
                        _normalizar(sibling.campo_padre or "")
                        == _normalizar(field.campo_padre or "")
                    )
                    for sibling_instruction in instructions_by_field.get(
                        sibling.id_campo, ()
                    )
                    if _normalizar(
                        sibling_instruction.documento_origen.replace(
                            "_", " "
                        )
                    ) not in {"contexto", "reglas negocio"}
                ))
                inherited_matches: list[
                    tuple[dict[str, Any], list[dict[str, Any]], str]
                ] = []
                for inherited_source in inherited_sources:
                    proxy = InstruccionExtraccion(
                        instruction.id_extraccion,
                        instruction.id_campo,
                        instruction.prioridad,
                        inherited_source,
                        instruction.regla_extraccion,
                        instruction.regla_validacion,
                        instruction.permite_ocr,
                        "No",
                        instruction.campo_destino,
                        instruction.observaciones,
                    )
                    for document in documents:
                        source_pages = pages_by_document.get(
                            str(document.get("documento", "")), []
                        )
                        match_kind = _source_match_kind(
                            proxy, document, source_pages
                        )
                        if match_kind is not None:
                            inherited_matches.append(
                                (document, source_pages, match_kind)
                            )
                unique_inherited: dict[
                    str,
                    tuple[dict[str, Any], list[dict[str, Any]], str],
                ] = {}
                for item in inherited_matches:
                    unique_inherited.setdefault(
                        str(item[0].get("documento", "")), item
                    )
                selected_documents = list(
                    unique_inherited.values()
                )
                inherited = bool(selected_documents)

            for _document, source_pages, match_kind in selected_documents:
                applicable += 1
                effective_pages = source_pages
                if match_kind == "estructural" and not inherited:
                    effective_pages = _structural_source_pages(
                        instruction, source_pages
                    )
                evidences.extend(_extract_values(
                    field,
                    instruction,
                    effective_pages,
                    related_labels,
                    inherited,
                    catalogs.get(field.catalogo_asociado or "", ()),
                ))

        best_quality: dict[tuple[str, str | None], int] = {}
        for evidence in evidences:
            quality_key = (evidence.documento, evidence.id_extraccion)
            best_quality[quality_key] = max(
                best_quality.get(quality_key, -10_000),
                evidence.calidad or 0,
            )
        evidences = [
            evidence for evidence in evidences
            if (evidence.calidad or 0) >= best_quality[
                (evidence.documento, evidence.id_extraccion)
            ] - 20
        ]
        unique_evidences: dict[
            tuple[str, str, int, str, str | None],
            EvidenciaExtraccion,
        ] = {}
        for evidence in evidences:
            key = (
                _normalizar(evidence.valor_encontrado),
                evidence.documento,
                evidence.pagina,
                evidence.evidencia_textual,
                evidence.id_extraccion,
            )
            previous = unique_evidences.get(key)
            if (
                previous is None
                or (evidence.calidad or 0) > (previous.calidad or 0)
            ):
                unique_evidences[key] = evidence
        field_values = tuple(sorted(
            unique_evidences.values(),
            key=lambda item: (
                item.prioridad if item.prioridad is not None else 999,
                item.documento,
                item.pagina,
                _normalizar(item.valor_encontrado),
            ),
        ))
        if field_values:
            status, observation = "Extraído", None
        elif not field_instructions:
            status, observation = (
                "No existe información",
                "El campo no tiene una instrucción de extracción en "
                "05_Extraccion_Documental.",
            )
        elif not applicable:
            status, observation = (
                "No existe información",
                "No se identificó un documento correspondiente al "
                "origen configurado.",
            )
        else:
            status, observation = (
                "No existe información",
                "No se encontró un valor con la evidencia disponible.",
            )
        results_by_id[field.id_campo] = ResultadoCampo(
            field,
            status,
            tuple(
                item.id_extraccion for item in field_instructions
            ),
            field_values,
            observation,
        )

    for field in attribute_fields:
        context_instructions = tuple(
            instruction
            for instruction in instructions_by_field[field.id_campo]
            if _normalizar(
                instruction.documento_origen.replace("_", " ")
            ) == "contexto"
        )
        if not context_instructions:
            continue
        siblings = tuple(
            result
            for result in results_by_id.values()
            if (
                result.campo.id_campo != field.id_campo
                and _normalizar(result.campo.campo_padre or "")
                == _normalizar(field.campo_padre or "")
            )
        )
        context_values: list[EvidenciaExtraccion] = []
        for instruction in context_instructions:
            options = _example_values(field, instruction)
            if not options:
                continue
            for sibling in siblings:
                for evidence in sibling.valores:
                    if (
                        isinstance(evidence.metodo, str)
                        and "ocr" in _normalizar(evidence.metodo)
                        and not _is_true(instruction.permite_ocr)
                    ):
                        continue
                    normalized_evidence = _normalizar(
                        evidence.evidencia_textual
                    )
                    for option in options:
                        if not re.search(
                            rf"(?<!\w){re.escape(_normalizar(option))}(?!\w)",
                            normalized_evidence,
                        ):
                            continue
                        context_values.append(EvidenciaExtraccion(
                            valor_encontrado=option,
                            documento=evidence.documento,
                            pagina=evidence.pagina,
                            metodo=evidence.metodo,
                            confianza=evidence.confianza,
                            evidencia_textual=evidence.evidencia_textual,
                            id_extraccion=instruction.id_extraccion,
                            documento_origen=instruction.documento_origen,
                            prioridad=_priority(instruction.prioridad),
                            heredado=False,
                            calidad=evidence.calidad,
                        ))
        if context_values:
            current = results_by_id[field.id_campo]
            combined = tuple(dict.fromkeys(
                (*current.valores, *context_values)
            ))
            results_by_id[field.id_campo] = ResultadoCampo(
                field,
                "Extraído",
                current.instrucciones,
                combined,
                None,
            )

    for field in fields:
        if _normalizar(field.nivel) != "entidad":
            continue
        children = tuple(
            result for result in results_by_id.values()
            if _normalizar(result.campo.campo_padre or "")
            == _normalizar(field.campo)
        )
        results_by_id[field.id_campo] = _consolidate_entity(
            field,
            children,
            instructions_by_field[field.id_campo],
        )
    results = tuple(results_by_id[field.id_campo] for field in fields)
    summary = _build_summary(fields, results)
    provisional = ResultadoExtraccion(expediente_id, results, warnings, "", summary)
    output = _write_result(configuration, provisional)
    logger = _extraction_logger(configuration.route("logs"))
    for result in results:
        logger.info("EXTRACCION CAMPO | %s | %s | %s evidencia(s)", result.campo.id_campo, result.estado, len(result.valores))
    for warning in warnings:
        logger.warning("ARQUITECTURA EXTRACCION | %s", warning)
    logger.info(
        "EXTRACCION COMPLETADA | %s | %s campo(s) | esquema_completo=%s | obligatorios_completos=%s",
        expediente_id,
        len(results),
        summary.esquema_completo,
        summary.cumple_campos_obligatorios,
    )
    return ResultadoExtraccion(
        expediente_id,
        results,
        warnings,
        output.relative_to(configuration.project_root).as_posix(),
        summary,
    )
