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
        # A short timeout and one retry: a slow or unreachable API must not keep the cashier waiting,
        # the rule-based path answers instead.
        self.client = (anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout, max_retries=1)
                       if settings.anthropic_api_key else None)

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
        except anthropic.APIError as exc:
            log.warning("Claude API error: %s", exc)
            return None
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude stopped with %s", resp.stop_reason)
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        try:
            out = json.loads(text) if text else None
        except ValueError:
            log.warning("Claude returned text that is not JSON")
            return None
        if not _matches(schema, out):
            log.warning("Claude's answer does not match the expected shape")
            return None
        return out


    def run_tools(self, system: str, task: str, tools: list[dict], call, done, effort: str = "medium",
                  max_turns: int = 12, max_tokens: int = 4000) -> list[dict] | None:
        """A tool-use loop: Claude picks which tool to call next, `call(name, input)` runs it in code and returns
        (result, ok), until `done()` is true or Claude stops. Returns the steps taken, or None when the API fails,
        Claude stops early, or the turn budget runs out, so the caller can fall back to its rules."""
        if not self.client:
            return None
        messages = [{"role": "user", "content": task}]
        steps = []
        for _ in range(max_turns):
            try:
                resp = self.client.beta.messages.create(
                    model=self.model, max_tokens=max_tokens, system=system, messages=messages, tools=tools,
                    output_config={"effort": effort}, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
            except anthropic.APIError as exc:
                log.warning("Claude API error during a tool loop: %s", exc)
                return None
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                log.warning("Claude stopped without finishing (%s)", resp.stop_reason)
                return None
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                schema = next((t["input_schema"] for t in tools if t["name"] == u.name), None)
                if schema is None or not _matches(schema, u.input):
                    result, ok = "That call does not match the tool's input. Check the tool description and try again.", False
                else:
                    result, ok = call(u.name, u.input)
                steps.append({"tool": u.name, "input": u.input, "ok": ok})
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(result, default=str),
                                "is_error": not ok})
            if done():
                return steps
            messages.append({"role": "user", "content": results})
        log.warning("Claude used every turn without finishing")
        return None


_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
          "null": type(None)}


def _matches(schema: dict, value) -> bool:
    """Checks the parts of JSON Schema the agents use (type, required, properties, items, enum, anyOf),
    so an answer of the wrong shape falls back to rules instead of breaking the agent."""
    if "anyOf" in schema:
        return any(_matches(s, value) for s in schema["anyOf"])
    if "enum" in schema and value not in schema["enum"]:
        return False
    types = schema.get("type")
    if types:
        types = types if isinstance(types, list) else [types]
        if not any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool)) for t in types):
            return False
    if isinstance(value, dict):
        if any(k not in value for k in schema.get("required", [])):
            return False
        return all(_matches(schema["properties"][k], v) for k, v in value.items() if k in schema.get("properties", {}))
    if isinstance(value, list) and "items" in schema:
        return all(_matches(schema["items"], v) for v in value)
    return True


def image_block(data: bytes, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()}}
