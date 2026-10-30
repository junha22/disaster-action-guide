"""POST /api/tts with a mocked Supertonic service (no real model, no network)."""
import json
import logging

from fastapi.testclient import TestClient
import httpx
import pytest

from app import tts as tts_module
from app.main import app
from app.tts import SupertonicTts, TtsUnavailable, get_tts, spoken_text

AUDIO = b"fLaC\x00fake-audio"


def service(calls, status=200, content=AUDIO):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(status, content=content)
    return httpx.MockTransport(handler)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("KIROTHON_TTS_URL", "http://tts.test")
    monkeypatch.delenv("KIROTHON_TTS_VOICE", raising=False)
    calls: list[dict] = []
    engine = SupertonicTts(transport=service(calls))
    app.dependency_overrides[get_tts] = lambda: engine
    with TestClient(app) as client:
        yield client, calls
    app.dependency_overrides.clear()


def test_returns_audio_with_voice_f1_sarah_in_korean(setup):
    client, calls = setup
    response = client.post("/api/tts", json={"text": "경로를 변경할까요?"})
    assert response.status_code == 200
    assert response.content == AUDIO and response.headers["content-type"] == "audio/flac"
    assert calls == [{"text": "경로를 변경할까요?", "voice": "F1", "lang": "ko", "speed": 1.05,
                      "response_format": "flac"}]


def test_same_sentence_is_served_from_the_cache(setup):
    client, calls = setup
    for _ in range(3):
        assert client.post("/api/tts", json={"text": "300m 앞에서 오른쪽입니다."}).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "가" * 301}, {"text": "안녕", "voice": "M1"}, {}])
def test_invalid_requests_are_422(setup, payload):
    client, calls = setup
    assert client.post("/api/tts", json=payload).status_code == 422
    assert calls == []


@pytest.mark.parametrize("transport", [
    httpx.MockTransport(lambda request: httpx.Response(500)),
    httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))),
    httpx.MockTransport(lambda request: httpx.Response(200, content=b"")),
])
def test_service_problems_are_503_without_echoing_text(setup, caplog, transport):
    client, _ = setup
    caplog.set_level(logging.DEBUG)
    app.dependency_overrides[get_tts] = lambda: SupertonicTts(transport=transport)
    response = client.post("/api/tts", json={"text": "북구 신안동 구간을 지나요."})
    assert response.status_code == 503 and response.json()["detail"] == "음성 합성을 사용할 수 없습니다"
    assert "신안동" not in response.text and "신안동" not in caplog.text


def test_empty_url_turns_the_voice_off(monkeypatch):
    monkeypatch.setenv("KIROTHON_TTS_URL", "")
    with pytest.raises(TtsUnavailable):
        SupertonicTts(transport=service([])).synthesize("안녕하세요.")


@pytest.mark.parametrize("text, expected", [
    ("강수 1단계 → 3단계", "강수 1단계 에서 3단계"),
    ("75mm · 1곳", "75밀리미터, 한 곳"),
    ("300m 앞, 2.5km 남음", "300미터 앞, 2.5킬로미터 남음"),
    ("(AI 설명) “안녕”", "AI 설명 안녕"),
    ("★☆", ""),
])
def test_spoken_text_removes_what_the_voice_cannot_read(text, expected):
    assert spoken_text(text) == expected


def test_default_service_is_loopback_only(monkeypatch):
    monkeypatch.delenv("KIROTHON_TTS_URL", raising=False)
    assert tts_module.settings().url == "http://127.0.0.1:7788"
