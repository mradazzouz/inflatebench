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
# The SDK refuses a non-streaming call it expects to run past 10 minutes: max_tokens above
# 21,333 (an hour per 128,000 tokens), or above a lower limit it keeps for some models.
NONSTREAMING_MAX_TOKENS = 21_333


def needs_streaming(model: str, max_tokens: int) -> bool:
    """Whether the SDK requires a streaming call for this model and max_tokens."""
    try:
        from anthropic._constants import MODEL_NONSTREAMING_TOKENS  # private, so optional
    except ImportError:
        MODEL_NONSTREAMING_TOKENS = {}  # noqa: N806
    limit = min(NONSTREAMING_MAX_TOKENS, MODEL_NONSTREAMING_TOKENS.get(model) or NONSTREAMING_MAX_TOKENS)
    return max_tokens > limit


def thinking_text(content: list[Any]) -> str:
    """Thinking blocks, kept for inspecting replies cut off at max_tokens. Empty when the model
    returns them with display "omitted" (the default on current models)."""
    parts = []
    for b in content:
        kind = getattr(b, "type", "")
        if kind == "thinking" and b.thinking:
            parts.append(b.thinking)
        elif kind == "redacted_thinking":
            parts.append("[redacted thinking]")
    return "\n\n".join(parts)


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
        params: dict[str, Any] | None = None,
        client: Any = None,
        retry_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.prices = prices or Prices()
        self.max_tokens = max_tokens
        self.prompt_cache = prompt_cache
        self.cache_ttl = cache_ttl
        self.extra = dict(params or {})  # extra request fields from config.yaml, sent on every call
        self.client = client if client is not None else make_client(api_key_env)
        self.retry_attempts = retry_attempts
        self.sleep = sleep

    def settings(self) -> dict[str, Any]:
        """Part of the cache key. Prompt caching changes cost, not answers, so it is left out."""
        settings = {"provider": "anthropic", "model": self.model, "max_tokens": self.max_tokens}
        # Only when set, so cache entries made without extra params keep their keys.
        return settings | ({"params": self.extra} if self.extra else {})

    def _retry(self, fn: Callable[[], Any]) -> Any:
        return retry(fn, attempts=self.retry_attempts, sleep=self.sleep)

    def params(self, messages: list[Message], kw: dict[str, Any]) -> dict[str, Any]:
        """Messages API request body. Temperature is left at the provider default unless given."""
        system, turns = to_chat(messages)
        kw = strip_key_only(kw)
        params: dict[str, Any] = {"model": self.model, "max_tokens": kw.pop("max_tokens", self.max_tokens)}
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
        return params | self.extra | kw

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
            thinking=thinking_text(msg.content),
            **tokens,
        )

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        params = self.params(messages, kw)
        if needs_streaming(self.model, params["max_tokens"]):
            return self._completion(self._retry(lambda: self._stream(params)))
        return self._completion(self._retry(lambda: self.client.messages.create(**params)))

    def _stream(self, params: dict[str, Any]) -> Any:
        """The final message of a streamed call: the same Message a non-streaming call returns."""
        with self.client.messages.stream(**params) as stream:
            return stream.get_final_message()

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        """Submit one batch; each entry's custom_id is its request hash (64 hex chars).

        Request.model is only a cache label (e.g. one per repeat); every entry goes to this
        provider's model.
        """
        unique = {r.key(): r for r in requests}
        body = [{"custom_id": k, "params": self.params(r.messages, dict(r.params))} for k, r in unique.items()]
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
