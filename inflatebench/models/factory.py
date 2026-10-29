"""Build a cached, logged provider from a `models:` entry in config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inflatebench.models import LLM
from inflatebench.models.cache import CachedLLM, DiskCache
from inflatebench.models.pricing import Prices
from inflatebench.models.usage import UsageLog

PROVIDERS = ("anthropic", "openai_compatible", "fake")
PLACEHOLDER = "CHANGE_ME"


def model_entry(cfg: dict[str, Any], key: str) -> dict[str, Any]:
    models = cfg.get("models") or {}
    if key not in models:
        raise KeyError(f"no model {key!r} in config; have {sorted(models)}")
    entry = dict(models[key])
    if entry.get("provider") not in PROVIDERS:
        raise ValueError(f"model {key!r}: provider must be one of {PROVIDERS}")
    if not entry.get("name") or entry["name"] == PLACEHOLDER:
        raise ValueError(f"model {key!r}: set its name in config.yaml")
    return entry


def build_provider(entry: dict[str, Any], prices: Prices) -> LLM:
    provider, name = entry["provider"], entry["name"]
    if provider == "anthropic":
        from inflatebench.models.anthropic import DEFAULT_MAX_TOKENS, AnthropicLLM

        return AnthropicLLM(
            name,
            prices=prices,
            max_tokens=entry.get("max_tokens", DEFAULT_MAX_TOKENS),
            prompt_cache=entry.get("prompt_cache", True),
            cache_ttl=entry.get("cache_ttl"),
            api_key_env=entry.get("api_key_env", "ANTHROPIC_API_KEY"),
        )
    if provider == "openai_compatible":
        from inflatebench.models.openai_compatible import OLLAMA_BASE_URL, OpenAICompatibleLLM

        return OpenAICompatibleLLM(
            name,
            base_url=entry.get("base_url", OLLAMA_BASE_URL),
            api_key_env=entry.get("api_key_env"),
            prices=prices,
            max_tokens=entry.get("max_tokens"),
        )
    from inflatebench.models.fake import FakeLLM

    return FakeLLM(entry.get("responses"), model=name)


def from_config(cfg: dict[str, Any], key: str, usage_path: str | Path | None = None) -> CachedLLM:
    """The model under `models.<key>`, cached on disk at paths.cache, logging to usage_path."""
    entry = model_entry(cfg, key)
    llm = build_provider(entry, Prices(cfg.get("prices")))
    cache = DiskCache((cfg.get("paths") or {}).get("cache", ".cache/requests"))
    return CachedLLM(llm, cache, model=f"{entry['provider']}:{entry['name']}", usage=UsageLog(usage_path))
