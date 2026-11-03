"""The backend's main module, however the app was loaded (HK-1).

Production starts the app through the repository-root shim (main.py), which
loads backend/main.py under the module name "backend_main"; the name "main"
belongs to the shim. A lazy `from main import x` therefore imported the shim
and failed in production only: the WhatsApp "send chase" action always
answered "Couldn't send the chase email automatically", and the profit guard's
alert emails could never send. Tests and local runs import backend/main.py as
"main", so they never saw it.

Code that needs a function from main.py calls backend_main().x instead.
"""
import importlib
import sys
from pathlib import Path

_MAIN = (Path(__file__).resolve().parent.parent / "main.py")


def _is(module, target) -> bool:
    path = getattr(module, "__file__", None)
    try:
        return bool(path) and Path(path).resolve() == target
    except OSError:
        return False


def backend_main(target: Path = _MAIN):
    """By file, under any name; also through the root shim's `backend_main`
    attribute, in case the shim ever stops registering it (Codex HK-1 review 1)."""
    for module in list(sys.modules.values()):
        if _is(module, target):
            return module
        inner = getattr(module, "backend_main", None)
        if inner is not None and not callable(inner) and _is(inner, target):
            return inner
    return importlib.import_module("main")
