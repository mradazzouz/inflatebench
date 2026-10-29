"""OpenAI-compatible chat completions provider; works with Ollama at http://localhost:11434/v1.

Uses the standard library for HTTP, so Ollama runs need no extra packages. There is no
batch API here: CachedLLM.run_batch falls back to sequential calls, caching each one.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from inflatebench.models import BatchError, BatchHandle, Completion, Request, strip_key_only
from inflatebench.models.chat import now, to_chat
from inflatebench.models.pricing import Prices
from inflatebench.models.retry import retry
from inflatebench.schema import Message

OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Takes (url, headers, json body) and returns the decoded JSON response.
Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class HTTPStatusError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"HTTP {status_code}: {body[:500]}")
        self.status_code = status_code


def urllib_transport(timeout: float = 600.0) -> Transport:
    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise HTTPStatusError(e.code, e.read().decode("utf-8", "replace")) from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"{url}: {e.reason}") from e

    return post


class OpenAICompatibleLLM:
    supports_batch = False

    def __init__(
        self,
        model: str,
        *,
        base_url: str = OLLAMA_BASE_URL,
        api_key_env: str | None = None,
        prices: Prices | None = None,
        max_tokens: int | None = None,
        transport: Transport | None = None,
        retry_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """api_key_env names the environment variable holding the key; None sends no key (Ollama)."""
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        if api_key_env:
            key = os.environ.get(api_key_env)
            if not key:
                raise RuntimeError(f"set {api_key_env} to use {base_url}")
            self.headers["Authorization"] = f"Bearer {key}"
        self.prices = prices or Prices()
        self.max_tokens = max_tokens
        self.post = transport or urllib_transport()
        self.retry_attempts = retry_attempts
        self.sleep = sleep
        self._batches: dict[str, dict[str, Completion | BatchError]] = {}

    def settings(self) -> dict[str, Any]:
        """Part of the cache key; the endpoint is included because it decides which weights answer."""
        return {"provider": "openai_compatible", "model": self.model, "url": self.url, "max_tokens": self.max_tokens}

    def params(self, messages: list[Message], kw: dict[str, Any], model: str | None = None) -> dict[str, Any]:
        system, turns = to_chat(messages)
        body: dict[str, Any] = {"model": model or self.model, "messages": ([{"role": "system", "content": system}] if system else []) + turns}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        return body | strip_key_only(kw)

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        body = self.params(messages, kw)
        data = retry(lambda: self.post(self.url, self.headers, body), attempts=self.retry_attempts, sleep=self.sleep)
        choice = data["choices"][0]
        u = data.get("usage") or {}
        cache_read = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        tokens = {
            "input_tokens": (u.get("prompt_tokens") or 0) - cache_read,
            "output_tokens": u.get("completion_tokens") or 0,
            "cache_read_tokens": cache_read,
        }
        return Completion(
            text=choice["message"].get("content") or "",
            model=data.get("model") or self.model,
            cost=self.prices.cost(self.model, **tokens),
            date=now(),
            stop_reason=choice.get("finish_reason") or "",
            **tokens,
        )

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        """No batch endpoint: runs the requests now and holds the results in memory."""
        handle = BatchHandle(id=f"local-{len(self._batches)}", size=len(requests))
        results: dict[str, Completion | BatchError] = {}
        for r in requests:
            try:
                results[r.key()] = self.complete(r.messages, **r.params)
            except Exception as e:  # noqa: BLE001 - reported per request, like a batch API
                results[r.key()] = BatchError(str(e), retryable=False)
        self._batches[handle.id] = results
        return handle

    def batch_done(self, handle: BatchHandle) -> bool:
        return True

    def batch_results(self, handle: BatchHandle) -> dict[str, Completion | BatchError]:
        return self._batches.pop(handle.id)
