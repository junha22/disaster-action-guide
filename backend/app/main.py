from contextlib import asynccontextmanager
from fastapi import FastAPI

from .database import DB_PATH, init_db
from .ai_service import ai_mode
from .schema_check import check_registered_schema
from .routers.records import router as records_router
from .routers.ai import router as ai_router
from .team import models as team_models  # noqa: F401 -- register before init_db
from .team.routes import router as team_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    ai_mode()
    check_registered_schema(DB_PATH)
    init_db()
    yield

app = FastAPI(
    title="Kirothon Starter API",
    version="1.1.0",
    lifespan=lifespan,
)

app.include_router(records_router)
app.include_router(ai_router)
app.include_router(team_router)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "kirothon-api", "ai_mode": ai_mode()}
