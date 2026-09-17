from __future__ import annotations

import os
import time
from typing import Any

import requests


def _text_from_response(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _quota_error(response: requests.Response) -> bool:
    text = response.text.lower()
    keys = ["insufficient_quota", "quota", "billing", "credit", "spend limit", "usage limit"]
    return any(k in text for k in keys)


def generate(prompt: str, settings: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("GPT_API_KEY", "").strip()
    model = str(settings.get("gpt_model", "")).strip()
    url = str(settings.get("gpt_base_url", "https://api.openai.com/v1/responses")).strip()
    if not key:
        return {"status": "error", "error": "Missing GPT_API_KEY", "model": model}
    if not model:
        return {"status": "error", "error": "Missing config.settings gpt_model", "model": model}

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": model, "input": prompt}
    max_tokens = int(settings.get("ai_max_output_tokens", 0) or 0)
    if max_tokens > 0:
        payload["max_output_tokens"] = max_tokens
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
            return {"status": "error", "error": "GPT response contained no text", "model": model, "raw": data}
        return {
            "status": "generated",
            "text": text,
            "model": model,
            "response_id": data.get("id"),
            "usage": data.get("usage"),
        }

    return {"status": "error", "error": "unreachable", "model": model}
