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


def backend_main():
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path:
            try:
                if Path(path).resolve() == _MAIN:
                    return module
            except OSError:
                continue
    return importlib.import_module("main")
