"""Punto de entrada de la inicialización de GIOJ."""

from __future__ import annotations

from pathlib import Path

from .bootstrap import initialize_project


def main() -> int:
    """Inicializa el proyecto y devuelve el código de salida correspondiente."""
    report = initialize_project(Path(__file__).resolve().parent.parent)
    print(report.to_console())
    return 0 if report.is_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
