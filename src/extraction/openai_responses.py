from __future__ import annotations

import json
import os
import socket
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.extraction.inference_profile import InferenceProfile
from src.extraction.model_runner import (
    ModelCallResult,
    ModelOutputError,
    OperationalModelError,
    ProviderContractError,
)


_ENDPOINT = "https://api.openai.com/v1/responses"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAIResponsesTransport:
    def __init__(
        self,
        *,
        api_key: str,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = 60,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(api_key=<redacted>, "
            f"timeout_seconds={self._timeout_seconds!r})"
        )

    @classmethod
    def from_environment(
        cls,
        profile: InferenceProfile,
        *,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = 60,
    ) -> "OpenAIResponsesTransport":
        api_key = os.environ.get(profile.secret_environment_variable)
        if not api_key:
            raise ValueError(
                f"required secret environment variable is missing: "
                f"{profile.secret_environment_variable}"
            )
        return cls(api_key=api_key, opener=opener, timeout_seconds=timeout_seconds)

    def __call__(
        self, document: dict[str, object], profile: InferenceProfile
    ) -> ModelCallResult:
        source_input = {
            field: document[field]
            for field in ("document_id", "source", "title", "text", "published_at")
        }
        body = {
            "model": profile.model,
            "reasoning": {"effort": profile.reasoning_effort},
            "input": [
                {"role": "system", "content": profile.prompt_text},
                {
                    "role": "user",
                    "content": json.dumps(source_input, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "problem_evidence_extraction",
                    "strict": True,
                    "schema": profile.output_schema,
                }
            },
            "max_output_tokens": profile.max_output_tokens,
            "store": False,
        }
        request = Request(
            _ENDPOINT,
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            if error.code in _RETRYABLE_STATUS:
                raise OperationalModelError(
                    f"OpenAI Responses API retryable HTTP status {error.code}"
                ) from error
            raise ProviderContractError(
                f"OpenAI Responses API non-retryable HTTP status {error.code}"
            ) from error
        except (URLError, TimeoutError, socket.timeout) as error:
            raise OperationalModelError("OpenAI Responses API transport failure") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderContractError("OpenAI response body is invalid") from error

        if not isinstance(payload, Mapping):
            raise ProviderContractError("OpenAI response must be an object")
        resolved_model = payload.get("model")
        if not isinstance(resolved_model, str) or not resolved_model.strip():
            raise ProviderContractError("OpenAI response resolved model is missing")
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            raise ProviderContractError("OpenAI response usage is missing")
        try:
            input_tokens = _token_count(usage.get("input_tokens"), "input")
            output_tokens = _token_count(usage.get("output_tokens"), "output")
        except ValueError as error:
            raise ProviderContractError("OpenAI response usage is invalid") from error
        try:
            output_text = _find_output_text(payload)
            structured = json.loads(output_text)
        except (ValueError, json.JSONDecodeError) as error:
            raise ModelOutputError(
                "OpenAI response output_text is missing or invalid",
                resolved_model=resolved_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ) from error
        if not isinstance(structured, Mapping):
            raise ModelOutputError(
                "OpenAI output_text must contain an object",
                resolved_model=resolved_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return ModelCallResult(
            output=dict(structured),
            resolved_model=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=str(payload["id"]) if payload.get("id") is not None else None,
        )


def _find_output_text(payload: Mapping[str, object]) -> str:
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, Mapping)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    return str(part["text"])
    raise ValueError("OpenAI response does not contain output_text")


def _token_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"OpenAI response {name} token usage is invalid")
    return value
