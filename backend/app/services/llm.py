"""LLM gateway: any OpenAI-compatible chat-completions endpoint.

Handles the operational realities the deck calls out: retries with backoff,
a fallback model chain, per-call timeouts, and graceful degradation. When no
endpoint is configured - or every attempt fails - ``complete`` returns ``None``
and the generation engine falls back to its deterministic extractive composer,
so the product never simply breaks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import get_settings


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    attempts: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Attempt:
    model: str
    ok: bool
    status_code: int | None = None
    error: str | None = None
    latency_ms: int = 0
    retry_in_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "ok": self.ok,
            "status_code": self.status_code,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "retry_in_ms": self.retry_in_ms,
        }


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some gateways return content parts
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or choices[0].get("text") or ""


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def configured(self) -> bool:
        return self.settings.llm_configured

    @property
    def mode(self) -> str:
        return "llm" if self.configured else "extractive"

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
        stop: list[str] | None = None,
    ) -> LLMResult | None:
        """Return generated text, or ``None`` if no model could serve the call."""
        if not self.configured:
            return None

        chain = [model_override] if model_override else self.settings.model_chain
        attempts: list[Attempt] = []
        started = time.perf_counter()

        for model in chain:
            result = self._call_model(
                model=model,
                system=system,
                user=user,
                temperature=self.settings.llm_temperature if temperature is None else temperature,
                max_tokens=max_tokens or self.settings.llm_max_output_tokens,
                stop=stop,
                attempts=attempts,
            )
            if result:
                return LLMResult(
                    text=result.strip(),
                    model=model,
                    provider=self.settings.llm_base_url,
                    attempts=[a.as_dict() for a in attempts],
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    prompt_tokens=result[1],
                    completion_tokens=result[2],
                )
        return None

    def _call_model(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        stop: list[str] | None,
        attempts: list[Attempt],
    ) -> tuple[str, int | None, int | None] | None:
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if stop:
            body["stop"] = stop

        for attempt_index in range(self.settings.llm_max_retries):
            attempt_started = time.perf_counter()
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=body)
                latency = int((time.perf_counter() - attempt_started) * 1000)

                if response.status_code >= 400:
                    retryable = response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                    attempts.append(
                        Attempt(
                            model=model,
                            ok=False,
                            status_code=response.status_code,
                            error=response.text[:300],
                            latency_ms=latency,
                        )
                    )
                    if not retryable:
                        return None
                else:
                    payload = response.json()
                    text = _extract_content(payload)
                    if not text.strip():
                        attempts.append(
                            Attempt(model=model, ok=False, status_code=response.status_code,
                                    error="empty completion", latency_ms=latency)
                        )
                    else:
                        attempts.append(
                            Attempt(model=model, ok=True, status_code=response.status_code, latency_ms=latency)
                        )
                        usage = payload.get("usage") or {}
                        return (
                            text,
                            usage.get("prompt_tokens"),
                            usage.get("completion_tokens"),
                        )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                attempts.append(
                    Attempt(
                        model=model,
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}"[:300],
                        latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                    )
                )
            except Exception as exc:
                attempts.append(Attempt(model=model, ok=False, error=f"{type(exc).__name__}: {exc}"[:300]))
                return None

            if attempt_index < self.settings.llm_max_retries - 1:
                backoff = min(8000, 500 * (2**attempt_index)) + int(time.perf_counter() * 137) % 250
                if attempts:
                    attempts[-1].retry_in_ms = backoff
                time.sleep(backoff / 1000)
        return None

    def health(self) -> str:
        if not self.configured:
            return "not_configured (deterministic extractive mode)"
        return f"configured ({', '.join(self.settings.model_chain)})"


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
