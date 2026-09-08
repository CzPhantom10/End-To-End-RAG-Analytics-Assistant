"""Groq LLM client.

Two jobs only: turn a question into a JSON analysis plan, and turn a computed
result table into business prose. It never produces numbers of its own - the
numbers always come from pandas.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .config import GROQ_API_KEY, GROQ_MODEL, NARRATOR_TEMPERATURE, PLANNER_TEMPERATURE

# Ordered fallbacks, tried when the configured model is retired or unavailable
# on the account. Groq retires models regularly, so this list matters.
MODEL_FALLBACKS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
]

# Substrings that mean "this model is unusable, try the next one"
MODEL_ERROR_MARKERS = ("does not exist", "not found", "decommission", "404", "no access", "deprecated")

# Reasoning models (gpt-oss, qwen3) emit a thinking block before the answer.
# It must be stripped, and the token budget must leave room for it.
THINK_BLOCK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
REASONING_HEADROOM = 3
# Keep latency usable: these are planning and summarising tasks, not proofs
REASONING_EFFORT = "low"


def strip_reasoning(text: str) -> str:
    """Remove a model's thinking block, keeping only the answer that follows."""
    cleaned = THINK_BLOCK.sub("", text).strip()
    # Anything after a stray closing tag is the real answer
    cleaned = re.split(r"</(?:think|thinking|reasoning)>", cleaned, flags=re.IGNORECASE)[-1].strip()
    # An unterminated block means the answer was cut off before it started
    if re.search(r"<(?:think|thinking|reasoning)>", cleaned, re.IGNORECASE):
        return ""
    return cleaned


class LLMError(Exception):
    """Raised when the model cannot be reached or returns nothing usable."""


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        # An explicit empty string means "no key"; only None falls back to .env
        self.api_key = (GROQ_API_KEY if api_key is None else api_key).strip()
        self.model = (model or GROQ_MODEL).strip() or MODEL_FALLBACKS[0]
        self._client = None
        self.last_model_used: str | None = None
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise LLMError(
                "No Groq API key configured. Add GROQ_API_KEY to the .env file "
                "and restart the app."
            )
        try:
            from groq import Groq
        except ImportError as exc:  # noqa: BLE001
            raise LLMError("The 'groq' package is not installed. Run: pip install groq") from exc
        self._client = Groq(api_key=self.api_key)
        return self._client

    # -- core call ---------------------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        json_mode: bool = False,
        max_tokens: int = 1600,
    ) -> str:
        client = self._ensure_client()
        models = [self.model] + [m for m in MODEL_FALLBACKS if m != self.model]
        last_error: Exception | None = None

        for model in models:
            # Attempts are ordered most-capable-first and degrade on failure:
            # low reasoning effort keeps latency down, strict JSON mode keeps the
            # planner parseable, and both are dropped if the model rejects them.
            supports_effort = "gpt-oss" in model or "qwen" in model
            attempts: list[tuple[bool, bool]] = []
            if json_mode:
                attempts.append((True, supports_effort))
                if supports_effort:
                    attempts.append((True, False))
                attempts.append((False, False))
            else:
                attempts.append((False, supports_effort))
                if supports_effort:
                    attempts.append((False, False))
            model_unavailable = False

            for use_json, use_effort in attempts:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    # Reasoning models spend part of the budget thinking
                    "max_tokens": max_tokens * REASONING_HEADROOM,
                }
                if use_json:
                    kwargs["response_format"] = {"type": "json_object"}
                if use_effort:
                    kwargs["reasoning_effort"] = REASONING_EFFORT
                try:
                    response = client.chat.completions.create(**kwargs)
                    content = strip_reasoning(response.choices[0].message.content or "")
                    if not content:
                        raise LLMError("empty completion")
                    self.last_model_used = model
                    self.last_error = None
                    return content
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self.last_error = f"{model}: {exc}"
                    message = str(exc).lower()
                    if any(marker in message for marker in MODEL_ERROR_MARKERS):
                        model_unavailable = True
                        break  # this model is gone; go to the next one
                    if "rate limit" in message or "429" in message:
                        model_unavailable = True
                        break  # try a different model rather than waiting

            # Both attempts failed for this model - move on to the next one
            _ = model_unavailable

        raise LLMError(f"Groq request failed: {last_error}")

    def list_models(self) -> list[str]:
        """Chat models this API key can actually use."""
        try:
            data = self._ensure_client().models.list().data
        except Exception:  # noqa: BLE001
            return []
        skip = ("whisper", "orpheus", "prompt-guard", "tts")
        return sorted(
            m.id
            for m in data
            if getattr(m, "context_window", 0) > 4000 and not any(s in m.id for s in skip)
        )

    # -- convenience -------------------------------------------------------

    def plan(self, system: str, user: str) -> dict[str, Any]:
        raw = self.complete(
            system, user, temperature=PLANNER_TEMPERATURE, json_mode=True, max_tokens=900
        )
        return parse_json(raw)

    def narrate(self, system: str, user: str) -> str:
        return self.complete(system, user, temperature=NARRATOR_TEMPERATURE, max_tokens=450)


def parse_json(raw: str) -> dict[str, Any]:
    """Parse a JSON object out of a model response, tolerating code fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {raw[:300]}") from exc
    raise LLMError(f"Model returned no JSON object: {raw[:300]}")
