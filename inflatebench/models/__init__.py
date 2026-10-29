"""LLM providers: anthropic (batch), openai_compatible (incl. Ollama), fake."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from inflatebench.schema import Message


@dataclass
class Request:
    """One model call; its hash is the disk-cache key."""

    model: str
    messages: list[Message]
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def key(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    date: str = ""
    cached: bool = False


@dataclass
class BatchHandle:
    id: str
    size: int


class LLM(Protocol):
    def complete(self, messages: list[Message], **kw: Any) -> Completion: ...  # logs model, tokens, cost

    def submit_batch(self, requests: list[Request]) -> BatchHandle: ...


from inflatebench.models.cache import CachedLLM, DiskCache  # noqa: E402
from inflatebench.models.fake import FakeLLM  # noqa: E402

__all__ = [
    "BatchHandle",
    "CachedLLM",
    "Completion",
    "DiskCache",
    "FakeLLM",
    "LLM",
    "Request",
]
