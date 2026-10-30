from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..context.kakao import KakaoSearch, get_search_service

router = APIRouter(prefix="/api", tags=["route"])


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=50)

    @field_validator("query", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.post("/search")
def search(body: SearchBody, service: Annotated[KakaoSearch, Depends(get_search_service)]):
    """The query travels in the POST body only (requirement 7.3) and is not logged."""
    return service.search(body.query)
