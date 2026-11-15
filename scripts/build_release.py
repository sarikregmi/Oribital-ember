#!/usr/bin/env python3
"""One-command release build: refresh full PSI snapshot, then package executable."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for script in ("build_psi_archive.py", "build_executable.py"):
    result = subprocess.call([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT)
    if result:
        raise SystemExit(result)
