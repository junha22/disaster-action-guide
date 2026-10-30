"""A student's own table/router can be added without editing protected files."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_team_extension_and_later_column_change(tmp_path):
    source = Path(__file__).resolve().parents[1] / "app"
    candidate = tmp_path / "backend"
    shutil.copytree(source, candidate / "app", ignore=shutil.ignore_patterns("__pycache__"))
    models = candidate / "app/team/models.py"
    models.write_text('''from sqlmodel import SQLModel, Field
class VerificationItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    label: str
''')
    (candidate / "app/team/routes.py").write_text('''from typing import Annotated
from fastapi import APIRouter, Depends
from sqlmodel import Session
from ..database import get_session
from .models import VerificationItem
router = APIRouter(prefix="/api/team")
@router.post("/verification")
def save(label: str, session: Annotated[Session, Depends(get_session)]):
    item = VerificationItem(label=label)
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id, "label": item.label}
''')
    env = dict(os.environ, KIROTHON_DB_PATH=str(tmp_path / "team.sqlite3"), KIROTHON_AI_MODE="mock")
    code = '''from fastapi.testclient import TestClient
from app.main import app
from app.database import engine
with TestClient(app) as client:
    assert client.get('/api/health').status_code == 200
    result = client.post('/api/team/verification', params={'label': 'isolated test'})
    assert result.status_code == 200, result.text
    assert result.json()['label'] == 'isolated test'
engine.dispose()
print('TEAM_EXTENSION_OK')
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=candidate, env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert "TEAM_EXTENSION_OK" in result.stdout
    # Changing a deployed column is not silently treated as an automatic migration.
    models.write_text(models.read_text() + "    category: str = ''\n")
    result = subprocess.run([sys.executable, "-m", "app.schema_check", "--database", env["KIROTHON_DB_PATH"]],
                            cwd=candidate, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode != 0
    assert "Schema review required" in result.stderr
