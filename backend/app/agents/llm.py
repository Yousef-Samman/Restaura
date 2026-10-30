"""Thin wrapper over the Claude API. Returns None when no key is configured or the call fails,
so every agent has a rule-based path and the app never stops working."""
import base64
import json
import logging

import anthropic

from ..config import Settings

log = logging.getLogger("restaura.llm")


class LLM:
    def __init__(self, settings: Settings):
        self.model = settings.model
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def json(self, system: str, content: list[dict] | str, schema: dict, effort: str = "low", max_tokens: int = 4000) -> dict | None:
        if not self.client:
            return None
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as exc:
            log.warning("Claude unreachable: %s", exc)
            return None
        except anthropic.APIStatusError as exc:
            log.warning("Claude API error %s: %s", exc.status_code, exc.message)
            return None
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude stopped with %s", resp.stop_reason)
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None


def image_block(data: bytes, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()}}
