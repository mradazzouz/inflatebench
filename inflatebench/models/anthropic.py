"""Anthropic provider: Messages API for single calls, Message Batches API for runs.

Prompt caching: breakpoints go on the system prompt, the last turn and the turn before it.
Repeats of one prompt then read the whole prompt from cache, and conditions that share a
history and differ only in the final instruction read the history.
Prefixes shorter than the model's minimum are silently not cached; that costs nothing.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from inflatebench.models import BatchError, BatchHandle, Completion, Request, strip_key_only
from inflatebench.models.chat import now, to_chat
from inflatebench.models.pricing import Prices
from inflatebench.models.retry import retry
from inflatebench.schema import Message

DEFAULT_MAX_TOKENS = 4096


def make_client(api_key_env: str = "ANTHROPIC_API_KEY") -> Any:
    key = os.environ.get(api_key_env)
    if not key:
        raise RuntimeError(f"set {api_key_env} to use the Anthropic provider")
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("pip install 'inflatebench[anthropic]' to use the Anthropic provider") from e
    # Retries are ours (models/retry.py), so they are uniform across providers and logged.
    return anthropic.Anthropic(api_key=key, max_retries=0)


class AnthropicLLM:
    supports_batch = True

    def __init__(
        self,
        model: str,
        *,
        prices: Prices | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        prompt_cache: bool = True,
        cache_ttl: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        client: Any = None,
        retry_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.prices = prices or Prices()
        self.max_tokens = max_tokens
        self.prompt_cache = prompt_cache
        self.cache_ttl = cache_ttl
        self.client = client if client is not None else make_client(api_key_env)
        self.retry_attempts = retry_attempts
        self.sleep = sleep

    def settings(self) -> dict[str, Any]:
        """Part of the cache key. Prompt caching changes cost, not answers, so it is left out."""
        return {"provider": "anthropic", "model": self.model, "max_tokens": self.max_tokens}

    def _retry(self, fn: Callable[[], Any]) -> Any:
        return retry(fn, attempts=self.retry_attempts, sleep=self.sleep)

    def params(self, messages: list[Message], kw: dict[str, Any], model: str | None = None) -> dict[str, Any]:
        """Messages API request body. Temperature is left at the provider default unless given."""
        system, turns = to_chat(messages)
        kw = strip_key_only(kw)
        params: dict[str, Any] = {"model": model or self.model, "max_tokens": kw.pop("max_tokens", self.max_tokens)}
        cc: dict[str, str] | None = None
        if self.prompt_cache:
            cc = {"type": "ephemeral"} | ({"ttl": self.cache_ttl} if self.cache_ttl else {})
        if system:
            params["system"] = [{"type": "text", "text": system} | ({"cache_control": cc} if cc else {})]
        msgs = [{"role": t["role"], "content": [{"type": "text", "text": t["content"]}]} for t in turns]
        if cc:
            for m in msgs[-2:]:
                m["content"][-1]["cache_control"] = cc
        params["messages"] = msgs
        return params | kw

    def _completion(self, msg: Any, batch: bool = False) -> Completion:
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        u = msg.usage
        tokens = {
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        return Completion(
            text=text,
            model=msg.model,
            cost=self.prices.cost(self.model, batch=batch, **tokens),
            date=now(),
            stop_reason=msg.stop_reason or "",
            batch=batch,
            **tokens,
        )

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        params = self.params(messages, kw)
        return self._completion(self._retry(lambda: self.client.messages.create(**params)))

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        """Submit one batch; each entry's custom_id is its request hash (64 hex chars)."""
        unique = {r.key(): r for r in requests}
        body = [{"custom_id": k, "params": self.params(r.messages, dict(r.params), r.model)} for k, r in unique.items()]
        batch = self._retry(lambda: self.client.messages.batches.create(requests=body))
        return BatchHandle(id=batch.id, size=len(body))

    def batch_done(self, handle: BatchHandle) -> bool:
        return self._retry(lambda: self.client.messages.batches.retrieve(handle.id)).processing_status == "ended"

    def batch_results(self, handle: BatchHandle) -> dict[str, Completion | BatchError]:
        out: dict[str, Completion | BatchError] = {}
        for entry in self._retry(lambda: list(self.client.messages.batches.results(handle.id))):
            res = entry.result
            if res.type == "succeeded":
                out[entry.custom_id] = self._completion(res.message, batch=True)
            elif res.type == "errored":
                err = getattr(res.error, "error", res.error)
                kind = getattr(err, "type", "") or ""
                out[entry.custom_id] = BatchError(
                    f"{kind}: {getattr(err, 'message', '')}", retryable="invalid_request" not in kind
                )
            else:  # canceled or expired
                out[entry.custom_id] = BatchError(res.type)
        return out
