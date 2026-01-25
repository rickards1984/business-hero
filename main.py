"""Shim entrypoint to load backend FastAPI app."""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_BACKEND_DIR = _ROOT / "backend"
_BACKEND_MAIN = _BACKEND_DIR / "main.py"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

spec = importlib.util.spec_from_file_location("backend_main", _BACKEND_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load backend main module from {_BACKEND_MAIN}")

backend_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend_main)

app = backend_main.app

print(f"[entrypoint] Loaded backend app from {_BACKEND_MAIN}")
