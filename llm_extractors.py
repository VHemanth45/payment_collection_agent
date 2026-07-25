"""Optional local Ollama and Anthropic extraction clients.

These clients only return structured candidates.  The Agent remains the sole
authority for validation, verification, state transitions, and API calls.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from extractor import ExtractionGroup, ExtractionRequest


def _prompt(request: ExtractionRequest) -> str:
    instructions = (
        "For identity extraction, return DOB as YYYY-MM-DD when the message "
        "contains an explicit natural-language date. Return only a clearly "
        "stated full name and never use conversational filler as a name."
        if request.group is ExtractionGroup.IDENTITY
        else ""
    )
    return (
        "Extract only the fields in this schema from the user message. "
        "Return one JSON object with every required property. Use null when "
        "a value is missing or unclear. Do not infer, verify, or invent values. "
        f"{instructions}\n\n"
        f"Schema:\n{json.dumps(request.schema, ensure_ascii=False)}\n\n"
        f"User message:\n{request.user_input}"
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class OllamaExtractor:
    """Schema-bound extractor using a local Ollama HTTP server."""

    allow_sensitive_data = True

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": request.schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": _prompt(request)},
            ],
        }
        response = self._post("/api/chat", payload)
        message = response.get("message", {}) if isinstance(response, dict) else {}
        return _json_object(message.get("content"))

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class AnthropicExtractor:
    """Schema-bound extractor using the Anthropic Messages API."""

    allow_sensitive_data = (
        os.getenv("PAYMENT_AGENT_ALLOW_SENSITIVE_LLM", "").strip().lower()
        in {"1", "true", "yes"}
    )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Claude extraction")
        self.model = model or os.getenv(
            "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
        )
        self.timeout = timeout

    def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": 300,
            "system": "Return only a JSON object matching the requested schema.",
            "messages": [{"role": "user", "content": _prompt(request)}],
        }
        http_request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        content = decoded.get("content", []) if isinstance(decoded, dict) else []
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return _json_object(text)


class AutomaticExtractor:
    """Best-effort provider chain used by the CLI without extra configuration.

    Providers are tried lazily only when the agent needs extraction. A failed
    provider is disabled for the remainder of the conversation, so an absent
    Ollama server or Claude API never changes the deterministic agent flow or
    causes repeated connection attempts.
    """

    allow_sensitive_data = True

    def __init__(self) -> None:
        timeout = float(os.getenv("PAYMENT_AGENT_LLM_TIMEOUT", "5"))
        self._providers: list[tuple[str, Any]] = [
            ("ollama", OllamaExtractor(timeout=timeout))
        ]
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                self._providers.append(("anthropic", AnthropicExtractor()))
            except ValueError:
                pass
        self._disabled: set[str] = set()

    def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        for name, provider in self._providers:
            if name in self._disabled:
                continue
            # Claude is never sent raw card fields unless the existing explicit
            # opt-in policy allows it. Ollama remains the local card fallback.
            if (
                request.group is ExtractionGroup.CARD
                and not getattr(provider, "allow_sensitive_data", False)
            ):
                continue
            try:
                result = provider.extract(request)
            except Exception:
                self._disabled.add(name)
                continue
            if isinstance(result, dict):
                return result
        return {}


def extractor_from_environment() -> OllamaExtractor | AnthropicExtractor | AutomaticExtractor:
    """Build an automatic provider chain; explicit settings remain overrides."""

    provider = os.getenv("PAYMENT_AGENT_LLM", "").strip().lower()
    if provider == "ollama":
        return OllamaExtractor()
    if provider in {"anthropic", "claude"}:
        return AnthropicExtractor()
    return AutomaticExtractor()
