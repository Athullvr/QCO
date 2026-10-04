"""Minimal provider-agnostic LLM client (plain `requests`, no SDK dependency) with a disk cache.
Providers: anthropic (Messages API, forced tool call = strict JSON) | openai (Chat Completions, also any OpenAI-compatible server via LLM_BASE_URL).
The model name is never hard-coded: set LLM_MODEL to the strongest model your account offers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

import requests


class LLM(Protocol):
    model: str
    def json_call(self, system: str, user: str, schema: dict, *, name: str = "result") -> dict: ...


class LLMError(RuntimeError): ...


class HttpLLM:
    def __init__(self, provider: str, api_key: str, model: str, *, base_url: str | None = None, cache_dir: Path | None = None,
                 timeout: float = 180, max_tokens: int = 4096):
        if not (provider and api_key and model): raise LLMError("LLM_PROVIDER, LLM_API_KEY and LLM_MODEL must all be set")
        self.provider, self.key, self.model, self.timeout, self.max_tokens = provider.lower(), api_key, model, timeout, max_tokens
        self.base = base_url or {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com"}.get(self.provider)
        if not self.base: raise LLMError(f"unknown provider {provider!r}; set LLM_BASE_URL for OpenAI-compatible servers")
        self.cache_dir = cache_dir
        if cache_dir: cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, *parts: str) -> str:
        return hashlib.sha256("\x00".join((self.provider, self.model, *parts)).encode()).hexdigest()

    def json_call(self, system: str, user: str, schema: dict, *, name: str = "result") -> dict:
        ck = self._key(system, user, json.dumps(schema, sort_keys=True))
        cf = self.cache_dir / f"{ck}.json" if self.cache_dir else None
        if cf and cf.exists(): return json.loads(cf.read_text())
        out = self._anthropic(system, user, schema, name) if self.provider == "anthropic" else self._openai(system, user, schema, name)
        if cf: cf.write_text(json.dumps(out))
        return out

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        if r.status_code >= 400: raise LLMError(f"{self.provider} HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def _anthropic(self, system, user, schema, name):
        j = self._post(f"{self.base}/v1/messages", {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                       {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0, "system": system,
                        "messages": [{"role": "user", "content": user}],
                        "tools": [{"name": name, "description": "Return the result.", "input_schema": schema}],
                        "tool_choice": {"type": "tool", "name": name}})
        for b in j.get("content", []):
            if b.get("type") == "tool_use": return b["input"]
        raise LLMError("no tool_use block in response")

    def _openai(self, system, user, schema, name):
        j = self._post(f"{self.base}/v1/chat/completions", {"Authorization": f"Bearer {self.key}"},
                       {"model": self.model, "temperature": 0,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}})
        return json.loads(j["choices"][0]["message"]["content"])


def build_llm(settings, cache_subdir: str = "llm") -> HttpLLM:
    return HttpLLM(settings.llm_provider, settings.llm_api_key.get_secret_value(), settings.llm_model,
                   base_url=settings.llm_base_url or None, cache_dir=settings.data_dir / "llm_cache" / cache_subdir)
