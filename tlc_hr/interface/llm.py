"""One place for the assistant's language model: a chain of OpenAI-compatible providers, best first.

Every feature asks this module and never a vendor. A provider joins the chain when its key is in the pod
environment, so a stronger model is one `kubectl create secret` plus one env name — no code change. The keyless
gateway and the Mistral key that shipped with the demo stay at the end so the assistant keeps answering when a free
tier throttles, and a throttled provider is skipped for a minute instead of slowing every reply.
"""

import json
import os
import re
import time

import frappe

# Best first. `keyless` providers answer without a signup; the rest appear in the chain only once their key exists.
PROVIDERS = (
    {"code": "llm7", "label": "LLM7 — free key, no card", "url": "https://api.llm7.io/v1/chat/completions",
     "model": "DeepSeek-V4.1-Flash", "key_env": "LLM7_API_KEY", "signup": "https://token.llm7.io"},
    {"code": "groq", "label": "Groq — free tier, 30 rpm", "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": "llama-3.3-70b-versatile", "key_env": "GROQ_API_KEY", "signup": "https://console.groq.com/keys"},
    {"code": "openrouter", "label": "OpenRouter — :free models", "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "nvidia/nemotron-3-ultra-550b-a55b:free", "key_env": "OPENROUTER_API_KEY",
     "signup": "https://openrouter.ai/workspaces/default/keys"},
    {"code": "gemini", "label": "Google Gemini — free tier",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "model": "gemini-2.0-flash", "key_env": "GEMINI_API_KEY", "signup": "https://aistudio.google.com/app/apikey"},
    {"code": "opencode", "label": "OpenCode Zen — free models", "url": "https://opencode.ai/zen/v1/chat/completions",
     "model": "flint-40b-free", "key_env": "OPENCODE_API_KEY", "signup": "https://opencode.ai/auth"},
    {"code": "pollinations", "label": "Free gateway — keyless, ~1 reply / 30 s / IP",
     "url": "https://text.pollinations.ai/openai", "model": "openai", "keyless": True, "json_flag": "jsonMode"},
    {"code": "mistral", "label": "Mistral — the key the demo shipped with",
     "url": "https://api.mistral.ai/v1/chat/completions", "model": "ministral-14b-latest",
     "key_env": "MISTRAL_API_KEY"},
)

THROTTLE_SECONDS = 35
_throttled = {}
_answered = {"code": "", "model": ""}


class _Throttled(Exception):
    pass


def _key(provider):
    return (os.environ.get(provider.get("key_env") or "", "") or "").strip()


def _model(provider):
    return (os.environ.get(f"TLC_AI_{provider['code'].upper()}_MODEL") or provider["model"]).strip()


def _usable(provider):
    return provider.get("keyless") or bool(_key(provider))


def chain():
    """The providers this pod can call, in the order they get their turn. TLC_AI_PROVIDER forces one."""
    providers = list(PROVIDERS)
    url = (os.environ.get("TLC_AI_BASE_URL") or "").strip()
    if url:
        providers.insert(0, {"code": "custom", "label": "TLC_AI_BASE_URL", "url": url.rstrip("/"),
                             "model": os.environ.get("TLC_AI_MODEL") or "openai", "keyless": True})
    forced = (os.environ.get("TLC_AI_PROVIDER") or "").strip()
    if forced:
        chosen = [item for item in providers if item["code"] == forced]
        if chosen:
            return chosen
    return providers


def _headers(provider):
    key = _key(provider) or (os.environ.get("TLC_AI_API_KEY") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _post(url, payload, headers=None, timeout=90):
    import requests

    response = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    if response.status_code in (401, 403):
        raise RuntimeError(f"bị từ chối {response.status_code}: {response.text[:120]}")
    if response.status_code in (402, 429, 503):
        raise _Throttled(response.status_code)
    response.raise_for_status()
    return response.json()


def _call(provider, messages, max_tokens, json_mode):
    payload = {"model": _model(provider), "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode:
        if provider.get("json_flag"):
            payload[provider["json_flag"]] = True
        else:
            payload["response_format"] = {"type": "json_object"}
    body = _post(provider["url"], payload, _headers(provider))
    return (body["choices"][0]["message"]["content"] or "").strip()


def chat(messages, max_tokens=800, json_mode=False):
    """One answer from the strongest provider reachable right now; plain text unless json_mode is asked."""
    errors, skipped = [], 0
    now = time.time()
    for provider in chain():
        if not _usable(provider):
            continue
        if now < _throttled.get(provider["code"], 0):
            skipped += 1
            continue
        try:
            answer = _call(provider, messages, max_tokens, json_mode)
        except _Throttled:
            _throttled[provider["code"]] = time.time() + THROTTLE_SECONDS
            skipped += 1
            errors.append(f"{provider['code']} hết lượt gọi")
            continue
        except Exception as exc:
            errors.append(f"{provider['code']}: {type(exc).__name__} {str(exc)[:120]}")
            continue
        _answered.update({"code": provider["code"], "model": _model(provider)})
        return answer
    if skipped and not errors:
        errors.append("mọi nhà cung cấp đang tạm nghỉ vì bị giới hạn số lượt")
    raise RuntimeError("Trợ lý không gọi được nhà cung cấp nào: " + "; ".join(errors))


def describe():
    """What the ledger should say answered: the provider that replied last, or the one that will answer next."""
    if _answered["code"]:
        return f"{_answered['model']} ({_answered['code']})"
    return _preview()


def _preview():
    now = time.time()
    for provider in chain():
        if _usable(provider) and now >= _throttled.get(provider["code"], 0):
            return f"{_model(provider)} ({provider['code']})"
    return "không có nhà cung cấp nào"


def providers(test=False, max_tokens=60):
    """Name each provider, whether this pod can call it, and — when asked — whether it really answers."""
    probe = [{"role": "system", "content": "Chỉ trả JSON."},
             {"role": "user", "content": f'Trả lời {{"ok":true,"year":<năm hiện tại>}}. Hôm nay là '
                                         f'{frappe.utils.getdate().isoformat()}.'}]
    rows = []
    for provider in chain():
        row = {"code": provider["code"], "label": provider.get("label", provider["code"]), "model": _model(provider),
               "key": bool(_usable(provider)), "signup": provider.get("signup", ""), "ready": _preview()}
        if not row["key"]:
            row["state"] = "thiếu key"
        elif test:
            started = time.time()
            try:
                row["answer"] = chat(probe, max_tokens=max_tokens, json_mode=True)
                row["state"] = "trả lời được"
            except Exception as exc:
                row["answer"] = ""
                row["state"] = f"lỗi: {str(exc)[:160]}"
            row["seconds"] = round(time.time() - started, 1)
        else:
            row["state"] = "sẵn sàng"
        rows.append(row)
    return rows


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
    for _attempt in range(2):
        raw = chat(messages, max_tokens=max_tokens, json_mode=True)
        parsed = _first_json(re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip())
        if isinstance(parsed, dict) and any(parsed.get(key) not in (None, "", []) for key in keys):
            return parsed
        messages = messages + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": "Chỉ trả lại đúng một JSON hợp lệ với các khóa "
                                + ", ".join(keys) + ". Không thêm chữ nào khác."}]
    frappe.throw("Trợ lý không trả JSON hợp lệ; thử lại hoặc kiểm tra hồ sơ.", frappe.ValidationError)
