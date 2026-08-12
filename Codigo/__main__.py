"""Punto de entrada de la inicialización de GIOJ."""

from __future__ import annotations

import argparse
from pathlib import Path

from .bootstrap import initialize_project
from .web import serve_interface, stop_interface


def main() -> int:
    """Ejecuta la inicialización o publica la interfaz local de GIOJ."""
    parser = argparse.ArgumentParser(prog="python -m Codigo")
    parser.add_argument(
        "comando",
        nargs="?",
        choices=("interfaz", "detener"),
        help="Inicia o detiene la interfaz local",
    )
    parser.add_argument("--puerto", type=int, default=0, help="Puerto local; 0 selecciona uno disponible")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent
    if args.comando == "interfaz":
        return serve_interface(project_root, args.puerto)
    if args.comando == "detener":
        return stop_interface(args.puerto or 8000)
    report = initialize_project(project_root)
    print(report.to_console())
    return 0 if report.is_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
