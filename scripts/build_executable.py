#!/usr/bin/env python3
"""Package Orbital Ember as a PyInstaller onedir executable.

Run on the target OS. The bundled PSI archive is included in the executable folder.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    separator = os.pathsep
    data = [
        f"{ROOT / 'app' / 'static'}{separator}app/static",
        f"{ROOT / 'app' / 'bundled_data' / 'psi'}{separator}app/bundled_data/psi",
    ]
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "OrbitalEmber", "--paths", str(ROOT), "--hidden-import", "app.main",
               "--collect-submodules", "app"]
    for item in data:
        command.extend(["--add-data", item])
    for package in ("fastapi", "uvicorn", "httpx", "pydantic", "webview", "PySide6", "qtpy"):
        command.extend(["--collect-all", package])
    command.append(str(ROOT / "desktop.py"))
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
