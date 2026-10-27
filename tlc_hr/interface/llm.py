"""One place for the assistant's language model.

The app talks to an OpenAI-compatible endpoint chosen by the environment: `TLC_AI_BASE_URL`, `TLC_AI_MODEL` and,
when the provider needs one, `TLC_AI_API_KEY`. The default is the keyless free gateway (text.pollinations.ai, which
serves a frontier OpenAI model), and the Mistral key that shipped with the demo stays as the fallback for the moments
the free tier throttles an IP (its free plan allows one reply per 30 seconds). The two are interchangeable because
both answer JSON, so a stronger key can be dropped in later without touching the features.
"""

import json
import os
import re
import time

import frappe

FREE_BASE = "https://text.pollinations.ai/openai"
FREE_MODEL = "openai"
FREE_JSON_FLAG = "jsonMode"
MISTRAL_BASE = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "ministral-14b-latest"

_throttled_until = 0.0


def settings():
    return {"base_url": (os.environ.get("TLC_AI_BASE_URL") or FREE_BASE).rstrip("/"),
            "model": os.environ.get("TLC_AI_MODEL") or FREE_MODEL,
            "api_key": os.environ.get("TLC_AI_API_KEY") or ""}


def describe():
    """What the ledger should say answered: the provider the caller will actually reach right now."""
    chosen = settings()
    if chosen["base_url"].startswith("https://text.pollinations.ai") and time.time() < _throttled_until:
        return f"{MISTRAL_MODEL} (mistral, free tier was throttling)"
    return chosen["model"]


class _Throttled(Exception):
    pass


def _post(url, payload, headers=None, timeout=90):
    import requests

    response = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    if response.status_code in (402, 429, 503):
        raise _Throttled(response.status_code, response.text[:200])
    response.raise_for_status()
    return response.json()


def _free_call(messages, max_tokens, json_mode):
    chosen = settings()
    payload = {"model": chosen["model"], "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode:
        payload[FREE_JSON_FLAG] = True
    headers = {"Authorization": f"Bearer {chosen['api_key']}"} if chosen["api_key"] else {}
    body = _post(chosen["base_url"], payload, headers)
    return (body["choices"][0]["message"]["content"] or "").strip()


def _mistral_call(messages, max_tokens, json_mode):
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Thiếu MISTRAL_API_KEY trong pod và nhà cung cấp chính đang bị giới hạn.")
    payload = {"model": MISTRAL_MODEL, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = _post(MISTRAL_BASE, payload, {"Authorization": f"Bearer {key}"})
    return (body["choices"][0]["message"]["content"] or "").strip()


def chat(messages, max_tokens=800, json_mode=False):
    """One answer from the best provider available right now; plain text unless json_mode is asked."""
    global _throttled_until
    errors = []
    if time.time() >= _throttled_until:
        try:
            return _free_call(messages, max_tokens, json_mode)
        except _Throttled as exc:
            _throttled_until = time.time() + 35
            errors.append(f"free {exc}")
        except Exception as exc:
            errors.append(f"free {type(exc).__name__}: {str(exc)[:120]}")
    try:
        return _mistral_call(messages, max_tokens, json_mode)
    except Exception as exc:
        errors.append(f"mistral {type(exc).__name__}: {str(exc)[:120]}")
    raise RuntimeError("Trợ lý không gọi được nhà cung cấp nào: " + "; ".join(errors))


def _first_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            return None


def chat_json(system, user, keys, max_tokens=1400):
    """A JSON object with the named keys, asking again when the model answers in prose."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = ""
    for attempt in range(2):
        raw = chat(messages, max_tokens=max_tokens, json_mode=True)
        parsed = _first_json(re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip())
        if isinstance(parsed, dict) and any(parsed.get(key) not in (None, "", []) for key in keys):
            return parsed
        messages = messages + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": "Chỉ trả lại đúng một JSON hợp lệ với các khóa "
                                + ", ".join(keys) + ". Không thêm chữ nào khác."}]
    frappe.throw("Trợ lý không trả JSON hợp lệ; thử lại hoặc kiểm tra hồ sơ.", frappe.ValidationError)
