"""Production installs the versions the tests ran on (8 Oct 2026 outage).

Railway runs `pip install -r requirements.txt` and nothing else. The lock
(`requirements.lock.txt`) was applied only in CI, so every deploy resolved
to the newest versions that day. SQLAlchemy 2.1 changed the default
PostgreSQL driver to psycopg, which is not installed, and every production
boot failed with "No module named 'psycopg'" — while CI, constrained to
2.0.52, stayed green.
"""

import re
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def _lines(path):
    return [ln.strip() for ln in path.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_railways_requirements_file_applies_the_lock():
    assert "-c requirements.lock.txt" in _lines(ROOT / "requirements.txt"), (
        "requirements.txt must carry `-c requirements.lock.txt`: it is the only "
        "file Railway installs (AGENTS.md §3.1)")


def test_the_lock_pins_the_database_stack_exactly():
    lock = (ROOT / "requirements.lock.txt").read_text()
    for name in ("SQLAlchemy", "sqlmodel", "psycopg2-binary"):
        assert re.search(rf"^{re.escape(name)}==\S+$", lock, re.M | re.I), \
            f"{name} must be pinned with == in requirements.lock.txt"


def test_the_database_url_names_the_installed_driver():
    from db import normalise_database_url
    for raw in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        url = normalise_database_url(raw)
        assert url.startswith("postgresql+psycopg2://"), url
        assert make_url(url).get_dialect().driver == "psycopg2"


def test_an_explicit_driver_is_left_alone():
    from db import normalise_database_url
    assert normalise_database_url("postgresql+asyncpg://h/db") == "postgresql+asyncpg://h/db"
    assert normalise_database_url("sqlite:///./x.db") == "sqlite:///./x.db"
