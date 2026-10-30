from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .database import DB_PATH, init_db
from .ai_service import ai_mode
from .schema_check import check_registered_schema
from .routers.records import router as records_router
from .routers.ai import router as ai_router
from .team import models as team_models  # noqa: F401 -- register before init_db
from .team.routes import router as team_router
from .api import routers as feature_routers

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
for feature_router in feature_routers:
    app.include_router(feature_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """422 without echoing request values (coordinates, search terms; requirement 7.4)."""
    detail = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "kirothon-api", "ai_mode": ai_mode()}
