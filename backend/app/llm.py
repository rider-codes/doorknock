"""One door to the language models. Each job (parse, chat, score, draft, people) has its own model chain.
Structured output comes from forcing a single tool call, with a plain-JSON fallback for models that ignore tools."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from . import config
from .db import session_scope
from .models import LlmCall

T = TypeVar("T", bound=BaseModel)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Raised for anything the user can act on (missing key, cap reached, bad output)."""


class _Retryable(Exception):
    """This model failed in a way another model might not (rate limit, outage, unusable output)."""


def _tokens_used_today() -> int:
    start = datetime.now(timezone.utc) - timedelta(hours=24)
    with session_scope() as s:
        total = s.execute(
            select(func.coalesce(func.sum(LlmCall.input_tokens + LlmCall.output_tokens), 0)).where(
                LlmCall.created_at >= start
            )
        ).scalar_one()
    return int(total)


def _log(purpose: str, model: str, input_tokens: int, output_tokens: int) -> None:
    with session_scope() as s:
        s.add(LlmCall(purpose=purpose, model=model, input_tokens=input_tokens or 0, output_tokens=output_tokens or 0))


def _extract_json(text: str) -> dict | None:
    """Pull a JSON object out of free text (models without tool support often wrap it in prose or a code fence)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    for candidate in (fence.group(1) if fence else None, text):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _call_anthropic(model, system, messages, schema, tool_name, max_tokens, purpose) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=config.anthropic_key(), max_retries=3)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=[{"name": tool_name, "description": "Return the result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
        )
    except anthropic.APIError as exc:
        raise _Retryable(f"Anthropic: {exc}") from exc
    _log(purpose, model, getattr(resp.usage, "input_tokens", 0), getattr(resp.usage, "output_tokens", 0))
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    raise _Retryable("Anthropic returned no structured output")


def _call_openrouter(model, system, messages, schema, tool_name, max_tokens, purpose) -> dict:
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *messages],
        "tools": [{"type": "function", "function": {"name": tool_name, "description": "Return the result.", "parameters": schema}}],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
    }
    headers = {
        "Authorization": f"Bearer {config.openrouter_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Doorknock",
    }
    last = ""
    for attempt in range(2):
        try:
            resp = httpx.post(OPENROUTER_URL, json=body, headers=headers, timeout=120)
        except httpx.HTTPError as exc:
            raise _Retryable(f"{model}: network error {type(exc).__name__}") from exc
        if resp.status_code == 429 and attempt == 0:
            time.sleep(2)  # free models are rate limited; one short wait, then move to the next model
            continue
        if resp.status_code in (401, 403):
            raise LLMError("OpenRouter rejected your key. Check it in Settings." if config.public_mode() else "OpenRouter rejected the API key. Check OPENROUTER_API_KEY.")
        if resp.status_code == 402:
            raise LLMError("OpenRouter says your key is out of credit. Add credit, or use a free key." if config.public_mode() else "OpenRouter says you are out of credit. Add credit, or pick free models in MODEL_* settings.")
        if resp.status_code >= 400:
            last = f"HTTP {resp.status_code}"
            raise _Retryable(f"{model}: {last}")
        break
    data = resp.json()
    if data.get("error"):
        raise _Retryable(f"{model}: {str(data['error'])[:120]}")
    usage = data.get("usage") or {}
    _log(purpose, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    choices = data.get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    for call in message.get("tool_calls") or []:
        args = (call.get("function") or {}).get("arguments")
        if isinstance(args, dict):
            return args
        parsed = _extract_json(args or "")
        if parsed is not None:
            return parsed
    parsed = _extract_json(message.get("content") or "")  # model ignored the tool and answered in text
    if parsed is not None:
        return parsed
    raise _Retryable(f"{model}: no usable structured output")


def _decode_nested(value):
    """Some models return an object as a JSON string ("role": "{\\"score\\": 10}"). Decode those, at any depth."""
    if isinstance(value, dict):
        return {k: _decode_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_nested(v) for v in value]
    if isinstance(value, str) and value.lstrip()[:1] in ("{", "["):
        try:
            return _decode_nested(json.loads(value))
        except ValueError:
            return value
    return value


def structured(
    *,
    purpose: str,
    system: str,
    user: str | list[dict],
    schema: dict,
    tool_name: str = "respond",
    max_tokens: int = 4096,
    accept=None,
) -> dict:
    """Ask a model for JSON matching `schema`. Tries this job's models in order until one answers.
    `accept(data)` may raise ValidationError to reject an answer and move on to the next model."""
    chain = config.model_chain(purpose)
    if not config.llm_ready():
        raise LLMError(
            "Add your OpenRouter key in Settings first (a free key works), then try again."
            if config.public_mode()
            else "No AI key is set. Add OPENROUTER_API_KEY (one key, many models) or ANTHROPIC_API_KEY to backend/.env "
            "and restart the server."
        )
    if _tokens_used_today() >= config.daily_token_cap():
        raise LLMError("Daily LLM token cap reached. Raise DAILY_TOKEN_CAP or wait 24 hours.")
    messages = [{"role": "user", "content": user}] if isinstance(user, str) else user

    problems: list[str] = []
    for model in chain:
        via_openrouter = config.uses_openrouter(model)
        if via_openrouter and not config.openrouter_key():
            problems.append(f"{model}: OPENROUTER_API_KEY is not set")
            continue
        if not via_openrouter and not config.anthropic_key():
            problems.append(f"{model}: ANTHROPIC_API_KEY is not set")
            continue
        call = _call_openrouter if via_openrouter else _call_anthropic
        try:
            data = call(model, system, messages, schema, tool_name, max_tokens, purpose)
        except _Retryable as exc:
            problems.append(str(exc))
            continue
        data = _decode_nested(data)
        if accept is not None:
            try:
                accept(data)
            except ValidationError:
                problems.append(f"{model}: answer did not match the expected shape")
                continue
        return data
    raise LLMError(f"No model could answer ({purpose}): " + "; ".join(problems))


def structured_model(
    model_cls: type[T],
    *,
    purpose: str,
    system: str,
    user: str | list[dict],
    max_tokens: int = 4096,
) -> T:
    """Like `structured`, validated against a pydantic model. One retry on a schema violation."""
    schema = model_cls.model_json_schema()
    last: Exception | None = None
    for attempt in range(2):
        note = "" if attempt == 0 else f"\n\nYour previous answer was invalid ({last}). Return valid JSON."
        data = structured(
            purpose=purpose, system=system + note, user=user, schema=schema, max_tokens=max_tokens, accept=model_cls.model_validate
        )
        try:
            return model_cls.model_validate(data)
        except ValidationError as exc:
            last = exc
    raise LLMError(f"The model returned invalid data twice: {last}")
