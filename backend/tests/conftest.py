"""Tests use temporary data only; no live AWS calls or server credentials."""
import os
from pathlib import Path
import sys
import tempfile

import pytest

scratch = tempfile.TemporaryDirectory(prefix="kirothon-r2-tests-")
os.environ["KIROTHON_DB_PATH"] = str(Path(scratch.name) / "records.sqlite3")
os.environ["KIROTHON_AI_MODE"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


@pytest.fixture(scope="session", autouse=True)
def isolated_data():
    yield
    engine.dispose()
    scratch.cleanup()
