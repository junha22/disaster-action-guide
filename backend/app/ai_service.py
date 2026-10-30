"""Shared bounded AI call. Local mock never falls back to AWS."""
import os
from typing import Literal

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from .ai_quota import QuotaExceeded, reserve_ai_request

AllowedModel = Literal[
    "global.anthropic.claude-sonnet-5-5",
    "global.anthropic.claude-sonnet-5",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.openai.gpt-6-sol",
    "global.openai.gpt-5.6-sol",
]
DEFAULT_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"


def ai_mode() -> str:
    mode = os.environ.get("KIROTHON_AI_MODE", "bedrock").strip().lower()
    if mode not in {"mock", "bedrock"}:
        raise RuntimeError("KIROTHON_AI_MODE must be mock or bedrock")
    return mode


def generate_text(text: str, instruction: str, model_id: str) -> dict:
    if not text.strip() or not instruction.strip():
        raise HTTPException(422, "Text and instruction must not be blank")
    if len(text) > 4000 or len(instruction) > 300:
        raise HTTPException(413, "Input or instruction is too long")
    mode = ai_mode()
    try:
        reserve_ai_request()
    except QuotaExceeded as exc:
        raise HTTPException(429, "AI 호출 한도 초과: 분당 20회 또는 하루 600회") from exc
    if mode == "mock":
        return {
            "text": "[로컬 모의 응답 — 실제 AI 결과가 아닙니다]\n"
                    "입력 전달과 화면 연동만 확인합니다. 실제 답변은 팀 서버에서 검증하세요.\n"
                    + text[:120],
            "model_id": model_id, "mode": "mock",
            "usage": {"inputTokens": 0, "outputTokens": 0},
        }
    try:
        client = boto3.client(
            "bedrock-runtime",
            # Compute region and Bedrock invocation region are separate settings.
            region_name=os.environ.get("KIROTHON_BEDROCK_REGION", "ap-northeast-1"),
            config=Config(connect_timeout=5, read_timeout=45, retries={"max_attempts": 1}),
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": instruction + "\n\n" + text}]}],
            inferenceConfig={"maxTokens": 256, "temperature": 0.2},
        )
    except (ClientError, BotoCoreError) as exc:
        code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
        raise HTTPException(429 if code == "ThrottlingException" else 502,
                            "Bedrock error: " + code) from exc
    content = response.get("output", {}).get("message", {}).get("content", [])
    result = "\n".join(item["text"] for item in content if "text" in item).strip()
    if not result:
        raise HTTPException(502, "Empty AI response")
    return {"text": result, "model_id": model_id, "mode": "bedrock",
            "usage": response.get("usage", {})}
