"""POST /api/tts: spoken guidance audio (Supertonic 3, voice F1 "Sarah"). Text goes in the POST body."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ..tts import MAX_TEXT, MEDIA_TYPE, SupertonicTts, TtsUnavailable, get_tts

router = APIRouter(prefix="/api", tags=["tts"])
UNAVAILABLE = "음성 합성을 사용할 수 없습니다"


class TtsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TEXT)


@router.post("/tts")
def tts(body: TtsBody, engine: Annotated[SupertonicTts, Depends(get_tts)]):
    try:
        audio = engine.synthesize(body.text)
    except TtsUnavailable:
        raise HTTPException(503, UNAVAILABLE) from None
    return Response(content=audio, media_type=MEDIA_TYPE, headers={"Cache-Control": "private, max-age=3600"})
