"""Carga segura de la configuración oficial del proyecto."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Indica que la configuración no puede consumirse de forma segura."""


def resolve_project_path(project_root: Path, configured_path: str) -> Path:
    """Resuelve una ruta relativa y evita que salga de la raíz del proyecto."""
    candidate = Path(configured_path)
    if candidate.is_absolute():
        raise ConfigurationError(f"La ruta debe ser relativa al proyecto: {configured_path}")
    root = project_root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ConfigurationError(f"La ruta sale de la raíz del proyecto: {configured_path}") from error
    return resolved


@dataclass(frozen=True)
class ProjectConfiguration:
    """Configuración y rutas verificadas de GIOJ."""

    project_root: Path
    source_path: Path
    values: dict[str, Any]

    def route(self, name: str) -> Path:
        try:
            configured_path = self.values["rutas"][name]
        except KeyError as error:
            raise ConfigurationError(f"Falta la ruta obligatoria: rutas.{name}") from error
        return resolve_project_path(self.project_root, configured_path)

    def file(self, name: str) -> Path:
        try:
            configured_path = self.values["archivos"][name]
        except KeyError as error:
            raise ConfigurationError(f"Falta el archivo obligatorio: archivos.{name}") from error
        return resolve_project_path(self.project_root, configured_path)

    @property
    def required_sheets(self) -> tuple[str, ...]:
        sheets = self.values.get("hojas")
        if not isinstance(sheets, dict) or not sheets:
            raise ConfigurationError("La sección hojas debe contener valores configurados")
        return tuple(str(sheet) for sheet in sheets.values())

    @property
    def template_paths(self) -> tuple[Path, Path]:
        directory = self.route("plantillas")
        try:
            names = (
                self.values["archivos"]["plantilla_conformidad"],
                self.values["archivos"]["plantilla_no_conformidad"],
            )
        except KeyError as error:
            raise ConfigurationError("Faltan nombres de plantillas obligatorias") from error
        return tuple(resolve_project_path(directory, name) for name in names)  # type: ignore[return-value]


def load_configuration(project_root: Path) -> ProjectConfiguration:
    """Lee ``Arquitectura/config.json`` sin alterar su contenido."""
    config_path = project_root / "Arquitectura" / "config.json"
    if not config_path.is_file():
        raise ConfigurationError("No se encontró Arquitectura/config.json")
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"No fue posible leer config.json: {error}") from error
    if not isinstance(values, dict):
        raise ConfigurationError("config.json debe contener un objeto JSON")
    return ProjectConfiguration(project_root.resolve(), config_path.resolve(), values)
