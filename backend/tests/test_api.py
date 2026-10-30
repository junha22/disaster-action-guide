import os
from unittest.mock import MagicMock, patch

from botocore.exceptions import NoCredentialsError
from fastapi.testclient import TestClient
import pytest

from app import ai_service
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


def create(client):
    response = client.post("/api/records", json={"title": "test", "content": "temporary"})
    assert response.status_code == 201
    return response.json()["id"]


def test_health(client):
    assert client.get("/api/health").json()["ai_mode"] == "mock"


def test_crud_and_restart(client):
    item = create(client)
    assert client.patch(f"/api/records/{item}", json={"content": "changed"}).status_code == 200
    assert client.get(f"/api/records/{item}").json()["content"] == "changed"
    assert item in [row["id"] for row in client.get("/api/records").json()]
    assert client.patch(f"/api/records/{item}", json={"title": None}).status_code == 422
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/records/{item}").json()["content"] == "changed"
    assert client.delete(f"/api/records/{item}").status_code == 204
    assert client.get(f"/api/records/{item}").status_code == 404


def test_standalone_mock_has_no_record_or_aws_call(client):
    before = client.get("/api/records").json()
    with patch.object(ai_service.boto3, "client") as factory:
        response = client.post("/api/ai/generate", json={"text": "verification"})
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert "모의 응답" in response.json()["text"]
    assert response.json()["usage"]["outputTokens"] == 0
    assert client.get("/api/records").json() == before
    factory.assert_not_called()


def test_record_ai_compatible_and_saved(client):
    item = create(client)
    response = client.post(f"/api/records/{item}/ai", json={"model_id": ai_service.DEFAULT_MODEL})
    assert response.status_code == 200
    assert response.json()["record_id"] == item
    assert client.get(f"/api/records/{item}").json()["ai_result"] == response.json()["ai_result"]


@pytest.mark.parametrize("payload", [
    {"text": ""}, {"text": " "}, {"text": "x" * 4001},
    {"text": "ok", "instruction": " "}, {"text": "ok", "instruction": "x" * 301},
    {"text": "ok", "model_id": "unapproved"},
])
def test_invalid_input_never_calls_aws(client, payload):
    with patch.object(ai_service.boto3, "client") as factory:
        assert client.post("/api/ai/generate", json=payload).status_code == 422
    factory.assert_not_called()


def test_quota_prevents_aws_for_both_routes(client):
    item = create(client)
    with patch.object(ai_service, "reserve_ai_request", side_effect=ai_service.QuotaExceeded("test")):
        with patch.object(ai_service.boto3, "client") as factory:
            assert client.post("/api/ai/generate", json={"text": "ok"}).status_code == 429
            assert client.post(f"/api/records/{item}/ai", json={}).status_code == 429
    factory.assert_not_called()


def test_bedrock_contract_uses_role_chain_and_bounded_output(client):
    fake = MagicMock()
    fake.converse.return_value = {"output": {"message": {"content": [{"text": "mocked provider"}]}}}
    with patch.dict(os.environ, {"KIROTHON_AI_MODE": "bedrock", "KIROTHON_BEDROCK_REGION": "ap-northeast-1"}):
        with patch.object(ai_service.boto3, "client", return_value=fake) as factory:
            response = client.post("/api/ai/generate", json={"text": "ok"})
    assert response.status_code == 200
    assert response.json()["mode"] == "bedrock"
    assert response.json()["text"] == "mocked provider"
    assert factory.call_args.kwargs["region_name"] == "ap-northeast-1"
    assert "aws_access_key_id" not in factory.call_args.kwargs
    assert fake.converse.call_args.kwargs["inferenceConfig"]["maxTokens"] == 256


def test_client_creation_error_is_sanitized(client):
    with patch.dict(os.environ, {"KIROTHON_AI_MODE": "bedrock"}):
        with patch.object(ai_service.boto3, "client", side_effect=NoCredentialsError()):
            response = client.post("/api/ai/generate", json={"text": "ok"})
    assert response.status_code == 502
    assert response.json()["detail"] == "Bedrock error: NoCredentialsError"


def test_invalid_mode_does_not_silently_call_aws():
    with patch.dict(os.environ, {"KIROTHON_AI_MODE": "typo"}):
        with patch.object(ai_service.boto3, "client") as factory:
            with pytest.raises(RuntimeError, match="KIROTHON_AI_MODE"):
                with TestClient(app):
                    pass
    factory.assert_not_called()


def test_windows_active_dependencies_are_pinned():
    """Audit Windows markers even when this test runs on Linux."""
    from importlib.metadata import PackageNotFoundError, distribution
    from pathlib import Path
    import re
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    lock = (Path(__file__).resolve().parents[1] / "requirements.local.lock").read_text()
    pins = {canonicalize_name(match.group(1)): match.group(2)
            for match in re.finditer(r'^([A-Za-z0-9_-]+)(?:\[[^]]+\])?==([^ ;\\\n]+)', lock, re.M)}
    assert pins["colorama"] == "0.4.6"
    assert 'colorama==0.4.6 ; sys_platform == "win32"' in lock
    assert "sha256:4f1d9991f5acc0ca119f9d443620b77f9d6b33703e51011c16baf57afb285fc6" in lock
    environment = default_environment()
    environment.update(sys_platform="win32", os_name="nt", platform_system="Windows",
                       platform_machine="AMD64", python_version="3.12", python_full_version="3.12.10")
    for name in pins:
        try:
            requires = distribution(name).requires or []
        except PackageNotFoundError:
            # Colorama is absent on Linux and has no dependencies in this pin.
            # uvloop is intentionally absent on Windows.
            assert name in {"colorama", "uvloop"}, name
            continue
        extras = ["", "standard"] if name == "uvicorn" else [""]
        for raw in requires:
            requirement = Requirement(raw)
            if requirement.marker and not any(
                    requirement.marker.evaluate(dict(environment, extra=extra)) for extra in extras):
                continue
            dep = canonicalize_name(requirement.name)
            assert dep in pins, f"Windows-only dependency missing from lock: {name} -> {raw}"
            assert requirement.specifier.contains(pins[dep]), f"Incompatible pin: {raw}"
