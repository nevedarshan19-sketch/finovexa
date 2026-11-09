from __future__ import annotations

import json

import httpx

from ...config import settings


class LLMUnavailable(Exception):
    pass


class LLMProvider:
    """OpenAI-compatible chat-completions adapter. Keys stay on the backend."""

    @property
    def configured(self) -> bool:
        return settings.llm_configured

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if not self.configured:
            raise LLMUnavailable("No LLM provider configured.")
        endpoint = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 900,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = httpx.post(
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise LLMUnavailable("The AI provider could not be reached.") from exc
        if response.status_code >= 400:
            raise LLMUnavailable(f"The AI provider returned an error ({response.status_code}).")
        try:
            choice = response.json()["choices"][0]["message"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMUnavailable("The AI provider returned an unexpected response.") from exc

        tool_calls = []
        for call in choice.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                {
                    "id": call.get("id") or f"call_{len(tool_calls)}",
                    "name": function.get("name") or "",
                    "arguments": args if isinstance(args, dict) else {},
                }
            )
        return {"content": choice.get("content"), "tool_calls": tool_calls}


provider = LLMProvider()
