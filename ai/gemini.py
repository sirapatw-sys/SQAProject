from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests


def _text_from_response(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for candidate in data.get("candidates", []) or []:
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _quota_error(response: requests.Response) -> bool:
    text = response.text.lower()
    keys = ["quota", "resource_exhausted", "rate limit", "per day", "billing"]
    return any(k in text for k in keys)


def generate(prompt: str, settings: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    model = str(settings.get("gemini_model", "")).strip()
    base_url = str(settings.get("gemini_base_url", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
    if not key:
        return {"status": "error", "error": "Missing GEMINI_API_KEY", "model": model}
    if not model:
        return {"status": "error", "error": "Missing config.settings gemini_model", "model": model}

    model_path = quote(model.removeprefix("models/"), safe="-_.")
    url = f"{base_url}/models/{model_path}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    generation_config: dict[str, Any] = {"temperature": 0}
    max_tokens = int(settings.get("ai_max_output_tokens", 0) or 0)
    if max_tokens > 0:
        generation_config["maxOutputTokens"] = max_tokens
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    retries = int(settings.get("api_max_retries", 4))
    timeout = int(settings.get("api_timeout_sec", 180))

    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            if attempt >= retries:
                return {"status": "error", "error": f"network_error: {exc}", "model": model}
            time.sleep(min(2 ** attempt, 16))
            continue

        if response.status_code == 429:
            if _quota_error(response) and attempt >= 1:
                return {"status": "paused_quota", "error": response.text[:1000], "model": model}
            if attempt < retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else min(2 ** attempt, 16)
                except ValueError:
                    wait = min(2 ** attempt, 16)
                time.sleep(wait)
                continue
            return {"status": "paused_quota", "error": response.text[:1000], "model": model}

        if response.status_code in {401, 403} and _quota_error(response):
            return {"status": "paused_quota", "error": response.text[:1000], "model": model}
        if response.status_code in {401, 403}:
            return {"status": "error", "error": f"HTTP {response.status_code}: {response.text[:1000]}", "model": model}
        if response.status_code >= 500 and attempt < retries:
            time.sleep(min(2 ** attempt, 16))
            continue
        if not response.ok:
            return {"status": "error", "error": f"HTTP {response.status_code}: {response.text[:1000]}", "model": model}

        try:
            data = response.json()
        except ValueError as exc:
            return {"status": "error", "error": f"invalid_json_response: {exc}", "model": model}
        text = _text_from_response(data)
        if not text:
            return {"status": "error", "error": "Gemini response contained no text", "model": model, "raw": data}
        return {
            "status": "generated",
            "text": text,
            "model": model,
            "usage": data.get("usageMetadata"),
        }

    return {"status": "error", "error": "unreachable", "model": model}
