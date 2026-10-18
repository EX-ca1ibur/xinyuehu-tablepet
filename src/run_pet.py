"""Entry point that works without installing the package.

Allows `pythonw.exe src/run_pet.py` (see start-pet.cmd) and also
`python -m pet.app` from inside src/.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# GUI process: never let an encoding hiccup kill it silently on Windows
os.environ.setdefault("PYTHONUTF8", "1")

from pet.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

