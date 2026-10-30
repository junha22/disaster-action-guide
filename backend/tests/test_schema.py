import hashlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from app import schema_check


def metadata(extra=False, changed_type=False):
    value = MetaData()
    columns = [Column("id", Integer, primary_key=True),
               Column("title", Integer if changed_type else String, nullable=False)]
    if extra:
        columns.append(Column("category", String))
    Table("team_item", value, *columns)
    return SimpleNamespace(metadata=value)


def database(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE team_item (id INTEGER PRIMARY KEY NOT NULL, title VARCHAR NOT NULL)")
        conn.execute("INSERT INTO team_item VALUES (1, 'preserve')")
    return path


def test_new_database_not_created_by_check(tmp_path):
    path = tmp_path / "absent.sqlite3"
    schema_check.check_registered_schema(path)
    assert not path.exists()


def test_same_schema_is_read_only(tmp_path):
    path = database(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with patch.object(schema_check, "SQLModel", metadata()):
        schema_check.check_registered_schema(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_new_team_table_allowed(tmp_path):
    path = database(tmp_path)
    models = metadata()
    Table("another_team_table", models.metadata, Column("id", Integer, primary_key=True))
    with patch.object(schema_check, "SQLModel", models):
        schema_check.check_registered_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='another_team_table'").fetchone() is None


@pytest.mark.parametrize("models", [metadata(extra=True), metadata(changed_type=True)])
def test_existing_column_changes_require_review(tmp_path, models):
    path = database(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with patch.object(schema_check, "SQLModel", models):
        with pytest.raises(RuntimeError, match="Schema review required"):
            schema_check.check_registered_schema(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
