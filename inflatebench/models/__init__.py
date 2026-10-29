"""LLM providers: anthropic (batch), openai_compatible (incl. Ollama), fake."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from inflatebench.schema import Message

# Params that only distinguish cache entries (e.g. repeat 0, 1, 2 of the same prompt);
# providers strip them before calling the API.
KEY_ONLY_PARAMS = frozenset({"repeat"})


@dataclass
class Request:
    """One model call; its hash is the disk-cache key.

    `params` are per-call arguments passed to the provider; `settings` are the provider's own
    configuration (model name, default max_tokens, endpoint), part of the key but never sent,
    so changing a setting in config.yaml never returns a stale cached answer.
    """

    model: str
    messages: list[Message]
    params: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Request:
        return cls(
            data["model"],
            [Message.from_dict(m) for m in data["messages"]],
            dict(data.get("params", {})),
            dict(data.get("settings", {})),
        )

    def key(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int = 0  # uncached input tokens
    output_tokens: int = 0
    cost: float = 0.0  # USD, from config.yaml prices; 0 when the model has no price
    date: str = ""  # ISO-8601 UTC time of the provider call
    cached: bool = False  # served from the disk cache
    cache_write_tokens: int = 0  # prompt-cache writes (Anthropic)
    cache_read_tokens: int = 0  # prompt-cache reads
    stop_reason: str = ""
    batch: bool = False  # produced through a batch API (discounted)


@dataclass
class BatchHandle:
    id: str
    size: int


class BatchError(Exception):
    """A batch entry that did not succeed; `retryable` says whether resubmitting may help."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLM(Protocol):
    def complete(self, messages: list[Message], **kw: Any) -> Completion: ...  # logs model, tokens, cost

    def submit_batch(self, requests: list[Request]) -> BatchHandle: ...


class BatchLLM(LLM, Protocol):
    """Providers with an asynchronous batch API; results are keyed by Request.key()."""

    def batch_done(self, handle: BatchHandle) -> bool: ...

    def batch_results(self, handle: BatchHandle) -> dict[str, Completion | BatchError]: ...


def strip_key_only(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if k not in KEY_ONLY_PARAMS}


def provider_settings(llm: Any) -> dict[str, Any]:
    """What a provider sends besides the per-call params; a provider without settings() gives its model."""
    settings = getattr(llm, "settings", None)
    return settings() if callable(settings) else {"model": getattr(llm, "model", None)}


from inflatebench.models.batch import Deferred, Pending, run_phases  # noqa: E402
from inflatebench.models.cache import CachedLLM, DiskCache  # noqa: E402
from inflatebench.models.factory import from_config, make_llm  # noqa: E402
from inflatebench.models.fake import FakeLLM  # noqa: E402
from inflatebench.models.pricing import Prices  # noqa: E402
from inflatebench.models.retry import retry  # noqa: E402
from inflatebench.models.usage import UsageLog  # noqa: E402

__all__ = [
    "BatchError",
    "BatchHandle",
    "BatchLLM",
    "CachedLLM",
    "Completion",
    "Deferred",
    "DiskCache",
    "FakeLLM",
    "LLM",
    "Pending",
    "Prices",
    "Request",
    "UsageLog",
    "from_config",
    "make_llm",
    "provider_settings",
    "retry",
    "run_phases",
    "strip_key_only",
]
