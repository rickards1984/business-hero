"""HK-1: code outside main.py reaches main.py's functions the way production
loads it. Production imports backend/main.py as "backend_main" (through the
repository-root shim, which owns the name "main"), so a lazy `from main import`
silently imported the shim and failed: WhatsApp chases and profit alerts never
sent. Tests import backend/main.py as "main", which is why none of them saw it.
"""
import re
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def test_no_backend_code_imports_main_by_name():
    pattern = re.compile(r"^\s*(from\s+main\s+import|import\s+main\b)", re.M)
    offenders = [str(p.relative_to(BACKEND)) for p in BACKEND.rglob("*.py")
                 if "tests" not in p.parts and p.name != "main.py" and pattern.search(p.read_text())]
    assert offenders == [], f"use services.backend_main.backend_main() instead: {offenders}"


def test_the_backend_main_module_is_found_as_production_loads_it(monkeypatch):
    from services.backend_main import backend_main
    shim = types.ModuleType("main")
    shim.__file__ = str(REPO / "main.py")                   # the root shim owns the name "main"
    real = types.ModuleType("backend_main")
    real.__file__ = str(BACKEND / "main.py")
    real.send_email_oauth = lambda *a: "sent"
    for name, module in list(sys.modules.items()):           # only the simulated modules may match
        if getattr(module, "__file__", None) and Path(module.__file__).resolve() == BACKEND / "main.py":
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "main", shim)
    monkeypatch.setitem(sys.modules, "backend_main", real)
    assert backend_main() is real
    assert backend_main().send_email_oauth() == "sent"


def test_the_chase_helper_and_profit_alert_use_the_resolver():
    for rel in ("services/invoice_chase_helper.py", "services/profit_guard.py"):
        assert "backend_main()" in (BACKEND / rel).read_text(), rel


def test_the_real_root_shim_is_resolved(tmp_path, monkeypatch):
    """Review 1: exercise the actual root main.py loading a stub backend, the
    way production does, without registering anything by hand."""
    from services.backend_main import backend_main
    (tmp_path / "backend").mkdir()
    (tmp_path / "main.py").write_text((REPO / "main.py").read_text())
    stub = tmp_path / "backend" / "main.py"
    stub.write_text("app = object()\ndef send_email_oauth(*a):\n    return 'sent'\n")
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in ("main", "backend_main"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import importlib.util
    spec = importlib.util.spec_from_file_location("main", tmp_path / "main.py")
    shim = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "main", shim)
    spec.loader.exec_module(shim)
    found = backend_main(stub.resolve())
    assert found is not shim and found.send_email_oauth() == "sent"


def test_a_shim_that_does_not_register_the_module_is_still_resolved(monkeypatch):
    from services.backend_main import backend_main
    real = types.ModuleType("hidden")
    real.__file__ = str(BACKEND / "main.py")
    shim = types.ModuleType("main")
    shim.__file__ = str(REPO / "main.py")
    shim.backend_main = real
    for name, module in list(sys.modules.items()):
        if getattr(module, "__file__", None) and Path(module.__file__).resolve() == BACKEND / "main.py":
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "main", shim)
    assert backend_main() is real
