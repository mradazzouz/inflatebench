"""FakeLLM: returns canned text so tests and cloud sessions need no API keys."""

from __future__ import annotations

from typing import Any, Callable

from inflatebench.models import BatchHandle, Completion, Request
from inflatebench.schema import Message

Responder = Callable[[list[Message]], str]


class FakeLLM:
    """Replies from a list of canned texts (cycled) or a function of the messages."""

    def __init__(self, responses: list[str] | Responder | None = None, model: str = "fake") -> None:
        self.responses = responses if responses is not None else ["ok"]
        self.model = model
        self.calls: list[list[Message]] = []
        self.batches: dict[str, list[Completion]] = {}

    def _text(self, messages: list[Message]) -> str:
        if callable(self.responses):
            return self.responses(messages)
        return self.responses[(len(self.calls) - 1) % len(self.responses)]

    def complete(self, messages: list[Message], **kw: Any) -> Completion:
        self.calls.append(list(messages))
        text = self._text(messages)
        return Completion(
            text=text,
            model=self.model,
            input_tokens=sum(len(m.content.split()) for m in messages),
            output_tokens=len(text.split()),
        )

    def submit_batch(self, requests: list[Request]) -> BatchHandle:
        handle = BatchHandle(id=f"fake-batch-{len(self.batches)}", size=len(requests))
        self.batches[handle.id] = [self.complete(r.messages, **r.params) for r in requests]
        return handle

    def batch_results(self, handle: BatchHandle) -> list[Completion]:
        return self.batches[handle.id]
