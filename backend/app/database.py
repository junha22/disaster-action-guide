import os
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

from .models import Record

DB_PATH = Path(
    os.environ.get(
        "KIROTHON_DB_PATH",
        str(Path.home() / "kirothon-data" / "records.sqlite3")
    )
).expanduser()

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

def init_db():
    DB_PATH.parent.mkdir(
        parents=True, exist_ok=True, mode=0o700
    )
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
