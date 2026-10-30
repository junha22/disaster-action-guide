from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..database import get_session
from ..models import Record
from ..ai_service import AllowedModel, DEFAULT_MODEL, generate_text

router = APIRouter(tags=["ai"])
SessionDep = Annotated[Session, Depends(get_session)]

class AIRequest(BaseModel):
    model_id: AllowedModel = DEFAULT_MODEL
    instruction: str = Field(
        default="입력의 핵심 내용을 한국어로 간결하게 정리해줘.",
        min_length=1,
        max_length=300,
    )

class GenerateRequest(AIRequest):
    text: str = Field(min_length=1, max_length=4000)

@router.post("/api/ai/generate")
def generate(data: GenerateRequest):
    """Independent AI API: does not create or update a Record."""
    return generate_text(data.text, data.instruction, data.model_id)

@router.post("/api/records/{record_id}/ai")
def process_ai(
    record_id: int,
    data: AIRequest,
    session: SessionDep,
):
    record = session.get(Record, record_id)

    if record is None:
        raise HTTPException(404, "Record not found")

    result = generate_text(f"제목: {record.title}\n내용: {record.content}",
                           data.instruction, data.model_id)
    record.ai_result = result["text"]
    record.updated_at = datetime.now(timezone.utc)

    session.add(record)
    session.commit()
    session.refresh(record)

    return {
        "record_id": record.id,
        "model_id": data.model_id,
        "ai_result": record.ai_result,
        "mode": result["mode"],
        "usage": result["usage"],
    }
