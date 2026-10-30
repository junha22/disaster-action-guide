from fastapi import APIRouter

# Add team endpoints to this router, e.g. @router.get('/...').
router = APIRouter(prefix="/api/team", tags=["team"])
