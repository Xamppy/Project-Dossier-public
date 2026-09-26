"""Cliente DeepSeek (API compatible con OpenAI Chat Completions)."""
from __future__ import annotations

import os
import time

from dossier.config import load_env
from dossier.llm.common import retry_after_seconds, should_retry

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_MAX_RETRIES = 4


def deepseek_api_key() -> str | None:
    load_env()
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    return key or None


def deepseek_model(override: str | None = None) -> str:
    load_env()
    return (override or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip()


def deepseek_base_url() -> str:
    load_env()
    return (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def deepseek_timeout_sec() -> float:
    load_env()
    raw = (os.getenv("DEEPSEEK_TEXT_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return max(10.0, float(raw))
        except ValueError:
            pass
    legacy_ms = (os.getenv("GEMINI_TEXT_TIMEOUT_MS") or "").strip()
    if legacy_ms.isdigit():
        return max(10.0, int(legacy_ms) / 1000.0)
    return DEFAULT_TIMEOUT_SEC


def chat_completion(
    user_prompt: str,
    *,
    system_instruction: str | None = None,
    model: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    json_mode: bool = False,
) -> str:
    key = deepseek_api_key()
    if not key:
        raise RuntimeError(
            "Falta DEEPSEEK_API_KEY en `.env` para la síntesis y análisis con IA."
        )

    from openai import OpenAI, omit

    client = OpenAI(api_key=key, base_url=deepseek_base_url())
    m = deepseek_model(model)
    timeout = deepseek_timeout_sec()

    messages: list[dict[str, str]] = []
    if system_instruction and system_instruction.strip():
        messages.append({"role": "system", "content": system_instruction.strip()})
    messages.append({"role": "user", "content": user_prompt})

    last_err: BaseException | None = None
    for attempt in range(max(1, max_retries)):
        try:
            response = client.chat.completions.create(
                model=m,
                messages=messages,  # type: ignore[arg-type]  # dict plano vs TypedDicts del SDK
                timeout=timeout,
                # DeepSeek exige que el prompt mencione "json" para aceptar este modo.
                response_format={"type": "json_object"} if json_mode else omit,
            )
            choice = response.choices[0] if response.choices else None
            text = (choice.message.content if choice and choice.message else None) or ""
            text = text.strip()
            if not text:
                raise RuntimeError("DeepSeek devolvió texto vacío.")
            return text
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1 and should_retry(e):
                time.sleep(retry_after_seconds(e))
                continue
            raise
    if last_err:
        raise last_err
    return ""
