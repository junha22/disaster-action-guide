"""Read-only column compatibility check, not an automatic migration system."""
import argparse
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel


def check_registered_schema(path: Path) -> None:
    path = path.expanduser().resolve()
    if not path.exists():
        return
    if not path.is_file():
        raise RuntimeError("SQLite path is not a regular file")
    uri = path.as_uri() + "?mode=ro"
    readonly = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with readonly.connect() as connection:
            inspector = inspect(connection)
            existing = set(inspector.get_table_names())
            for name, table in SQLModel.metadata.tables.items():
                if name not in existing:
                    continue
                actual = {column["name"]: column for column in inspector.get_columns(name)}
                if set(actual) != set(table.columns.keys()):
                    raise RuntimeError(f"Schema review required: column set changed in {name}")
                for column in table.columns:
                    old = actual[column.name]
                    expected_type = str(column.type.compile(dialect=connection.dialect)).upper()
                    nullable = old["nullable"] and not old.get("primary_key")
                    if (expected_type != str(old["type"]).upper()
                            or bool(column.nullable) != bool(nullable)
                            or bool(column.primary_key) != bool(old.get("primary_key"))):
                        raise RuntimeError(f"Schema review required: column changed in {name}.{column.name}")
    finally:
        readonly.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    from .main import app  # noqa: F401 -- register models, not the lifespan
    check_registered_schema(args.database)
    print("SCHEMA_COLUMN_COMPATIBILITY_OK")


if __name__ == "__main__":
    main()
