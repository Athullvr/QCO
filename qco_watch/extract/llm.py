"""Minimal provider-agnostic LLM client (plain `requests`, no SDK dependency) with a disk cache and token accounting.
Providers: anthropic (Messages API, forced tool call = strict JSON) | openai (Chat Completions; ANY OpenAI-compatible endpoint via LLM_BASE_URL,
e.g. Gemini: https://generativelanguage.googleapis.com/v1beta/openai ).
For provider=openai, base_url is the full prefix before '/chat/completions' (default https://api.openai.com/v1).
json_mode: 'json_schema' (response_format with the schema, $refs inlined) | 'json_object' (schema given in the prompt; for endpoints that reject json_schema).
The model name is never hard-coded: set LLM_MODEL."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Protocol

import requests


class LLM(Protocol):
    model: str
    def json_call(self, system: str, user: str, schema: dict, *, name: str = "result") -> dict: ...


class LLMError(RuntimeError): ...


def inline_refs(schema: dict) -> dict:
    """Resolve $ref/$defs (some OpenAI-compatible servers, e.g. Gemini's, handle them poorly) and drop 'title' noise."""
    defs = schema.get("$defs", {})

    def walk(n):
        if isinstance(n, dict):
            if "$ref" in n: return walk(defs[n["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in n.items() if k not in ("$defs", "title")}
        return [walk(x) for x in n] if isinstance(n, list) else n
    return walk(schema)


class HttpLLM:
    def __init__(self, provider: str, api_key: str, model: str, *, base_url: str | None = None, cache_dir: Path | None = None,
                 timeout: float = 180, max_tokens: int = 4096, json_mode: str = "json_schema", retries: int = 3):
        if not (provider and api_key and model): raise LLMError("LLM_PROVIDER, LLM_API_KEY and LLM_MODEL must all be set")
        if json_mode not in ("json_schema", "json_object"): raise LLMError("json_mode must be json_schema or json_object")
        self.provider, self.key, self.model, self.timeout, self.max_tokens = provider.lower(), api_key, model, timeout, max_tokens
        self.json_mode, self.retries = json_mode, retries
        if self.provider not in ("anthropic", "openai"): raise LLMError(f"unknown provider {provider!r}; use 'openai' + LLM_BASE_URL for compatible servers")
        default = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1"}[self.provider]
        self.base = (base_url or default).rstrip("/")
        self.cache_dir = cache_dir
        if cache_dir: cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        self.usage = {"calls": 0, "cached_calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _key(self, *parts: str) -> str:
        return hashlib.sha256("\x00".join((self.provider, self.base, self.model, self.json_mode, *parts)).encode()).hexdigest()

    def json_call(self, system: str, user: str, schema: dict, *, name: str = "result") -> dict:
        ck = self._key(system, user, json.dumps(schema, sort_keys=True))
        cf = self.cache_dir / f"{ck}.json" if self.cache_dir else None
        if cf and cf.exists():
            d = json.loads(cf.read_text()); out, u = d["output"], d["usage"]
            self.usage["cached_calls"] += 1
        else:
            self._last = (0, 0)
            out = self._anthropic(system, user, schema, name) if self.provider == "anthropic" else self._openai(system, user, schema, name)
            u = {"input_tokens": self._last[0], "output_tokens": self._last[1]}
            if cf: cf.write_text(json.dumps({"output": out, "usage": u}))
        # tokens are counted even for cache hits so cost reflects what a fresh run would bill
        self.last_usage = u
        self.usage["input_tokens"] += u["input_tokens"]; self.usage["output_tokens"] += u["output_tokens"]
        return out

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        for attempt in range(self.retries):
            r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                time.sleep(2 ** (attempt + 1)); continue
            break
        if r.status_code >= 400: raise LLMError(f"{self.provider} HTTP {r.status_code}: {r.text[:300]}")
        j = r.json(); self.usage["calls"] += 1
        return j

    def _anthropic(self, system, user, schema, name):
        j = self._post(f"{self.base}/v1/messages", {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                       {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0, "system": system,
                        "messages": [{"role": "user", "content": user}],
                        "tools": [{"name": name, "description": "Return the result.", "input_schema": schema}],
                        "tool_choice": {"type": "tool", "name": name}})
        u = j.get("usage", {}); self._last = (u.get("input_tokens", 0), u.get("output_tokens", 0))
        for b in j.get("content", []):
            if b.get("type") == "tool_use": return b["input"]
        raise LLMError("no tool_use block in response")

    def _openai(self, system, user, schema, name):
        flat = inline_refs(schema)
        if self.json_mode == "json_schema":
            rf, sys_msg = {"type": "json_schema", "json_schema": {"name": name, "schema": flat}}, system
        else:
            rf, sys_msg = {"type": "json_object"}, system + "\n\nReturn ONLY a JSON object that conforms to this JSON Schema:\n" + json.dumps(flat)
        j = self._post(f"{self.base}/chat/completions", {"Authorization": f"Bearer {self.key}"},
                       {"model": self.model, "temperature": 0, "response_format": rf,
                        "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]})
        u = j.get("usage", {}); self._last = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        txt = j["choices"][0]["message"]["content"] or ""
        try: return json.loads(txt)
        except json.JSONDecodeError as e: raise LLMError(f"invalid JSON from model: {e}; head={txt[:120]!r}") from e


def build_llm(settings, cache_subdir: str = "llm", **over) -> HttpLLM:
    kw = dict(provider=settings.llm_provider, api_key=settings.llm_api_key.get_secret_value(), model=settings.llm_model,
              base_url=settings.llm_base_url or None, json_mode=settings.llm_json_mode, cache_dir=settings.data_dir / "llm_cache" / cache_subdir)
    kw.update(over)
    return HttpLLM(kw.pop("provider"), kw.pop("api_key"), kw.pop("model"), **kw)
