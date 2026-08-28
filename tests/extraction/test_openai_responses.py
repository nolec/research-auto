from __future__ import annotations

import io
import json
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src.extraction.inference_profile import load_inference_profile
from src.extraction.model_runner import (
    ModelOutputError,
    OperationalModelError,
    ProviderContractError,
)
from src.extraction.openai_responses import (
    OpenAIResponsesTransport,
    build_response_request_body,
)


ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_inference_profile(
    ROOT / "configs/extraction/inference-profile-gpt-5.6-v1.json"
)
DOCUMENT = {
    "document_id": "github:1",
    "source": "github",
    "title": "Operation fails",
    "text": "The operation fails every time.",
    "published_at": "2026-01-01T00:00:00Z",
    "source_url": "https://secret.example/source/1",
}


class Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def _model_output() -> dict[str, object]:
    text = str(DOCUMENT["text"])
    return {
        "document_id": DOCUMENT["document_id"],
        "observation_type": "user_problem",
        "actor": "source author",
        "problem": text,
        "context": str(DOCUMENT["title"]),
        "consequence": text,
        "evidence_quote": text,
        "evidence_start": 0,
        "evidence_end": len(text),
        "problem_signal": True,
        "money_signal": False,
        "money_signal_type": None,
        "usable_evidence": True,
        "confidence": 0.9,
        "abstention_reason": None,
    }


def test_transport_uses_strict_responses_schema_without_persisting_source_url() -> None:
    observed: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> Response:
        observed["request"] = request
        observed["timeout"] = timeout
        return Response(
            {
                "id": "resp-secret",
                "model": "gpt-5.6-2026-08-01",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": json.dumps(_model_output())}
                        ]
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )

    transport = OpenAIResponsesTransport(
        api_key="top-secret", opener=opener, timeout_seconds=30
    )
    result = transport(DOCUMENT, PROFILE)

    request = observed["request"]
    body = json.loads(request.data)
    assert body == build_response_request_body(DOCUMENT, PROFILE)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.headers["Authorization"] == "Bearer top-secret"
    assert body["model"] == "gpt-5.6"
    assert body["store"] is False
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    schema_bytes = json.dumps(
        body["text"]["format"]["schema"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert sha256(schema_bytes).hexdigest() == PROFILE.output_schema_sha256
    assert "https://secret.example" not in json.dumps(body)
    assert result.output == _model_output()
    assert result.resolved_model == "gpt-5.6-2026-08-01"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.request_id == "resp-secret"


def test_transport_reads_key_from_environment_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    transport = OpenAIResponsesTransport.from_environment(
        PROFILE, opener=lambda *_args, **_kwargs: Response({})
    )
    assert "environment-secret" not in repr(transport)


def test_transport_uses_prompt_frozen_in_profile_without_rereading_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def opener(request: object, **_kwargs: object) -> Response:
        observed["body"] = json.loads(request.data)
        return Response(
            {
                "id": "hidden",
                "model": "gpt-5.6",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_model_output()),
                            }
                        ]
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )

    def reject_prompt_reread(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("prompt reread")

    monkeypatch.setattr(Path, "read_text", reject_prompt_reread)
    OpenAIResponsesTransport(api_key="secret", opener=opener)(DOCUMENT, PROFILE)

    assert observed["body"]["input"][0]["content"] == PROFILE.prompt_text


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transport_classifies_retryable_http_status_without_body_leak(status: int) -> None:
    def opener(*_args: object, **_kwargs: object) -> Response:
        raise HTTPError(
            "https://api.openai.com/v1/responses",
            status,
            "failure",
            {},
            io.BytesIO(b'{"error":"secret response body"}'),
        )

    transport = OpenAIResponsesTransport(api_key="secret", opener=opener)
    with pytest.raises(OperationalModelError, match=str(status)) as error:
        transport(DOCUMENT, PROFILE)
    assert "secret response body" not in str(error.value)


def test_transport_returns_sanitized_output_error_on_missing_output_text() -> None:
    transport = OpenAIResponsesTransport(
        api_key="secret",
        opener=lambda *_args, **_kwargs: Response(
            {
                "id": "hidden",
                "model": "gpt-5.6",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ),
    )
    with pytest.raises(ModelOutputError, match="output_text") as error:
        transport(DOCUMENT, PROFILE)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "hidden",
            "model": "gpt-5.6",
            "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
        },
        {
            "id": "hidden",
            "model": "gpt-5.6",
            "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
            "usage": {"input_tokens": 1},
        },
    ],
)
def test_transport_fails_closed_when_usage_is_missing_or_incomplete(
    payload: dict[str, object],
) -> None:
    transport = OpenAIResponsesTransport(
        api_key="secret", opener=lambda *_args, **_kwargs: Response(payload)
    )
    with pytest.raises(ProviderContractError, match="usage"):
        transport(DOCUMENT, PROFILE)


def test_transport_fails_closed_when_resolved_model_is_missing() -> None:
    payload = {
        "id": "hidden",
        "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    transport = OpenAIResponsesTransport(
        api_key="secret", opener=lambda *_args, **_kwargs: Response(payload)
    )
    with pytest.raises(ProviderContractError, match="resolved model"):
        transport(DOCUMENT, PROFILE)


def test_transport_classifies_non_retryable_http_status_as_provider_contract_error() -> None:
    def opener(*_args: object, **_kwargs: object) -> Response:
        raise HTTPError(
            "https://api.openai.com/v1/responses",
            400,
            "failure",
            {},
            io.BytesIO(b'{"error":"secret response body"}'),
        )

    transport = OpenAIResponsesTransport(api_key="secret", opener=opener)
    with pytest.raises(ProviderContractError, match="400") as error:
        transport(DOCUMENT, PROFILE)
    assert "secret response body" not in str(error.value)
