from __future__ import annotations

import os
import time
from typing import Any

import requests


def _chat_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _text_from_response(data: dict[str, Any]) -> str:
    # KKU IntelSphere uses an OpenAI-compatible chat-completions response.
    choices = data.get("choices", []) or []
    if choices:
        message = choices[0].get("message", {}) or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            return "\n".join(chunks).strip()

    # Compatibility fallbacks in case the gateway response shape changes.
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)

    for candidate in data.get("candidates", []) or []:
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)

    return "\n".join(chunks).strip()


def _hard_quota_error(response: requests.Response) -> bool:
    """True only for non-transient quota/billing exhaustion, not ordinary rate limiting."""
    text = response.text.lower()
    keys = [
        "insufficient_quota",
        "credit_balance_exhausted",
        "daily quota",
        "daily limit",
        "per day",
        "requests per day",
        "tokens per day",
        "quota exhausted",
        "quota has been exhausted",
        "billing",
        "credit",
        "spend limit",
    ]
    return any(key in text for key in keys)


def generate(prompt: str, settings: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("GPT_API_KEY", "").strip()
    model = str(settings.get("gpt_model", "")).strip()
    base_url = str(settings.get("gpt_base_url", "")).strip()

    if not key:
        return {
            "status": "error",
            "error": "Missing GPT_API_KEY (KKU IntelSphere API key)",
            "model": model,
        }
    if not model:
        return {
            "status": "error",
            "error": "Missing config/settings.json gpt_model",
            "model": model,
        }
    if not base_url:
        return {
            "status": "error",
            "error": "Missing config/settings.json gpt_base_url",
            "model": model,
        }

    url = _chat_url(base_url)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }

    max_tokens = int(settings.get("ai_max_output_tokens", 0) or 0)
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens

    retries = int(settings.get("api_max_retries", 2))
    timeout = int(settings.get("api_timeout_sec", 120))

    for attempt in range(retries + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if attempt >= retries:
                return {
                    "status": "error",
                    "error": f"network_error: {exc}",
                    "model": model,
                }
            time.sleep(min(2 ** attempt, 8))
            continue

        if response.status_code == 429:
            # Daily/credit exhaustion should pause this provider for the process.
            # Ordinary RPM/TPM throttling is transient: honor Retry-After and retry.
            if _hard_quota_error(response):
                return {
                    "status": "paused_quota",
                    "error": response.text[:1000],
                    "model": model,
                }

            if attempt < retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else min(2 ** attempt, 8)
                except ValueError:
                    wait = min(2 ** attempt, 8)
                time.sleep(max(0.0, min(wait, 60.0)))
                continue

            return {
                "status": "error",
                "error": f"rate_limit_after_retries: {response.text[:1000]}",
                "model": model,
            }

        if response.status_code in {401, 403} and _hard_quota_error(response):
            return {
                "status": "paused_quota",
                "error": response.text[:1000],
                "model": model,
            }
        if response.status_code in {401, 403}:
            return {
                "status": "error",
                "error": f"HTTP {response.status_code}: {response.text[:1000]}",
                "model": model,
            }

        if response.status_code >= 500 and attempt < retries:
            time.sleep(min(2 ** attempt, 8))
            continue

        if not response.ok:
            return {
                "status": "error",
                "error": f"HTTP {response.status_code}: {response.text[:1000]}",
                "model": model,
            }

        try:
            data = response.json()
        except ValueError as exc:
            return {
                "status": "error",
                "error": f"invalid_json_response: {exc}",
                "model": model,
            }

        text = _text_from_response(data)
        if not text:
            return {
                "status": "error",
                "error": "KKU GPT response contained no text",
                "model": model,
                "raw": data,
            }

        return {
            "status": "generated",
            "text": text,
            "model": model,
            "response_id": data.get("id"),
            "usage": data.get("usage") or data.get("usageMetadata"),
            "quota": data.get("model_quota") or data.get("quota"),
        }

    return {"status": "error", "error": "unreachable", "model": model}
