"""
Shared pytest configuration and fixtures for the PolyMind backend test suite.

The backend modules use top-level imports (`from config import ...`,
`from db.models import ...`), so they expect `backend/` to be importable. We add
it to `sys.path` here, before any test module is collected, so tests can import
the package exactly the way the application does.

We also force PAPER_MODE on for the whole session — no test should ever be able
to place a real order — and point the SQLite database at a throwaway temp file so
tests never touch a developer's real `polymind.db`.
"""
import os
import sys
from pathlib import Path

import pytest

# ── Make backend/ importable (one level up from this tests/ package) ──────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ── Safety: never let the suite touch live trading or a real key ─────────────
# Set before any backend module imports `config`, so these defaults win.
os.environ.setdefault("PAPER_MODE", "true")
os.environ.setdefault("VIRTUALS_API_KEY", "test-key")


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Point db.models at a fresh, isolated SQLite file and initialize the schema.

    Yields the path to the temp database. Each test that requests this fixture
    gets its own empty, migrated database — nothing is shared between tests and
    the developer's real polymind.db is never touched.
    """
    import db.models as models

    db_file = tmp_path / "test_polymind.db"
    monkeypatch.setattr(models, "DB_PATH", str(db_file))
    models.init_db()
    yield db_file
