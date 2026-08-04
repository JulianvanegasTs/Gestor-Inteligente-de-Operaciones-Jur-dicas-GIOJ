"""Inicialización, validación y diagnóstico base de GIOJ."""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .config import ConfigurationError, ProjectConfiguration, load_configuration


@dataclass(frozen=True)
class Diagnostic:
    status: str
    subject: str
    detail: str


@dataclass
class StartupReport:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return not any(item.status == "ERROR" for item in self.diagnostics)

    def add(self, status: str, subject: str, detail: str) -> None:
        self.diagnostics.append(Diagnostic(status, subject, detail))

    def to_console(self) -> str:
        state = "LISTO" if self.is_ready else "NO LISTO"
        lines = [f"GIOJ — estado de inicio: {state}"]
        lines.extend(f"[{item.status}] {item.subject}: {item.detail}" for item in self.diagnostics)
        return "\n".join(lines)


def _create_logger(log_directory: Path) -> logging.Logger:
    """Crea el registro de arranque en la carpeta de logs configurada."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"gioj.bootstrap.{log_directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_directory / "inicializacion.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _configured_directories(configuration: ProjectConfiguration) -> tuple[Path, ...]:
    names = ("plantillas", "expedientes", "conocimiento", "salida", "logs", "codigo")
    directories = tuple(configuration.route(name) for name in names)
    testing_workspace = configuration.route("expedientes") / "Pruebas" / "02_Trabajo"
    return (*directories, testing_workspace)


def _read_workbook_sheets(architecture_path: Path) -> set[str]:
    """Obtiene los nombres de hojas de un XLSX con la biblioteca estándar."""
    namespace = {"sheet": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(architecture_path) as workbook:
            workbook_xml = workbook.read("xl/workbook.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ValueError(f"El archivo no es un libro XLSX válido: {error}") from error
    root = ElementTree.fromstring(workbook_xml)
    return {
        sheet.attrib["name"]
        for sheet in root.findall("sheet:sheets/sheet:sheet", namespace)
        if "name" in sheet.attrib
    }


def _validate_required_files(configuration: ProjectConfiguration, report: StartupReport) -> None:
    report.add("OK", "Configuración", str(configuration.source_path.relative_to(configuration.project_root)))
    for name in configuration.values.get("archivos", {}):
        if name.startswith("plantilla_"):
            continue
        path = configuration.file(name)
        report.add("OK" if path.is_file() else "ERROR", f"Archivo {name}", "encontrado" if path.is_file() else "no encontrado")


def _validate_architecture(configuration: ProjectConfiguration, report: StartupReport) -> None:
    architecture_path = configuration.route("arquitectura")
    if not architecture_path.is_file():
        report.add("ERROR", "Arquitectura.xlsx", "no encontrado")
        return
    try:
        available_sheets = _read_workbook_sheets(architecture_path)
    except ValueError as error:
        report.add("ERROR", "Arquitectura.xlsx", str(error))
        return
    report.add("OK", "Arquitectura.xlsx", "libro válido")
    for sheet in configuration.required_sheets:
        report.add("OK" if sheet in available_sheets else "ERROR", f"Hoja {sheet}", "encontrada" if sheet in available_sheets else "no encontrada")


def _validate_templates(configuration: ProjectConfiguration, report: StartupReport) -> None:
    for path in configuration.template_paths:
        report.add("OK" if path.is_file() else "ERROR", f"Plantilla {path.name}", "encontrada" if path.is_file() else "no encontrada")


def initialize_project(project_root: Path) -> StartupReport:
    """Prepara directorios, logs y validaciones sin modificar archivos oficiales."""
    report = StartupReport()
    try:
        configuration = load_configuration(project_root)
        directories = _configured_directories(configuration)
    except ConfigurationError as error:
        report.add("ERROR", "Configuración", str(error))
        return report
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        report.add("OK", "Directorio", str(directory.relative_to(configuration.project_root)))
    logger = _create_logger(configuration.route("logs"))
    _validate_required_files(configuration, report)
    _validate_architecture(configuration, report)
    _validate_templates(configuration, report)
    for diagnostic in report.diagnostics:
        (logger.error if diagnostic.status == "ERROR" else logger.info)("%s | %s | %s", diagnostic.status, diagnostic.subject, diagnostic.detail)
    return report
