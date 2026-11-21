"""Talks to the AI service the admin configured. Provider-based: every kind implements stream() and models().
`openai` covers OpenAI itself and every OpenAI-compatible API (Azure-style gateways, Groq, OpenRouter, Together,
Gemini's compatible endpoint, a local Ollama or LM Studio) by changing the base URL."""
import base64
import hashlib
import json
from typing import Iterator

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class AIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---- key storage -------------------------------------------------------------------------
def _fernet() -> Fernet:
    secret = (settings.AI_KEY_SECRET or settings.JWT_SECRET).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"workcode-ai-key:" + secret).digest()))


def encrypt_key(key: str) -> str:
    return _fernet().encrypt(key.encode()).decode()


def decrypt_key(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise AIError(503, "The stored AI key cannot be read (the server secret changed). "
                           "An administrator must enter the key again in AI settings.")


# ---- HTTP --------------------------------------------------------------------------------
def make_client() -> httpx.Client:      # replaced in tests by a mock transport
    return httpx.Client(timeout=httpx.Timeout(settings.AI_TIMEOUT_SECONDS, connect=10))


def _explain(status: int, body: str) -> AIError:
    """Turn a provider error into one sentence for the user. The API key is never part of the message."""
    detail = ""
    try:
        err = json.loads(body).get("error")
        detail = (err.get("message") if isinstance(err, dict) else str(err or ""))[:200]
    except Exception:
        detail = body[:200]
    low = detail.lower()
    if status in (401, 403):
        return AIError(502, "The AI provider rejected the API key. An administrator must check it in AI settings.")
    if status == 429:
        if "quota" in low or "billing" in low or "credit" in low:
            return AIError(429, "The AI account has no credit left (provider quota). An administrator must check billing.")
        return AIError(429, "The AI provider is busy (rate limit). Wait a little and try again.")
    if status in (400, 413) and ("context" in low or "too long" in low or "maximum" in low or "token" in low):
        return AIError(413, "The request is too large for this model. Send less context (fewer files) or start a new chat.")
    if status == 404:
        return AIError(502, f"The AI provider does not know this model or address. {detail}".strip())
    if status >= 500:
        return AIError(502, "The AI provider has a problem right now. Try again in a moment.")
    return AIError(502, f"The AI provider refused the request ({status}). {detail}".strip())


def _network(e: Exception) -> AIError:
    if isinstance(e, httpx.TimeoutException):
        return AIError(504, "The AI provider did not answer in time. Try again.")
    return AIError(502, "Cannot reach the AI provider. Check the address in AI settings and the server's internet connection.")


class OpenAICompatible:
    kind = "openai"

    @staticmethod
    def _headers(key: str) -> dict:
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def stream(self, base_url: str, key: str, model: str, messages: list[dict], max_tokens: int) -> Iterator[tuple]:
        """Yields ("delta", text) and finally ("usage", {"prompt": n, "completion": n}) when the provider reports it."""
        url = base_url.rstrip("/") + "/chat/completions"
        limit = "max_completion_tokens" if "api.openai.com" in base_url else "max_tokens"
        full = {"model": model, "messages": messages, "stream": True, limit: max_tokens,
                "stream_options": {"include_usage": True}}
        plain = {"model": model, "messages": messages, "stream": True}
        with make_client() as client:
            for attempt, payload in enumerate((full, plain)):
                try:
                    with client.stream("POST", url, headers=self._headers(key), json=payload) as r:
                        if r.status_code >= 400:
                            body = r.read().decode(errors="replace")
                            err = _explain(r.status_code, body)
                            # some compatible servers do not know the optional fields: retry once without them
                            if r.status_code == 400 and attempt == 0 and err.status != 413:
                                continue
                            raise err
                        for line in r.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                            except ValueError:
                                continue
                            if chunk.get("error"):
                                raise _explain(500, json.dumps(chunk))
                            for choice in chunk.get("choices") or []:
                                text = (choice.get("delta") or {}).get("content")
                                if text:
                                    yield ("delta", text)
                            u = chunk.get("usage")
                            if u:
                                yield ("usage", {"prompt": u.get("prompt_tokens") or 0,
                                                 "completion": u.get("completion_tokens") or 0})
                        return
                except httpx.HTTPError as e:
                    raise _network(e)

    def models(self, base_url: str, key: str) -> list[str]:
        try:
            with make_client() as client:
                r = client.get(base_url.rstrip("/") + "/models", headers=self._headers(key))
        except httpx.HTTPError as e:
            raise _network(e)
        if r.status_code >= 400:
            raise _explain(r.status_code, r.text)
        try:
            return sorted(m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id"))
        except Exception:
            raise AIError(502, "The address answered, but not like an OpenAI-compatible API.")


KINDS = {"openai": OpenAICompatible()}


def stream_chat(kind: str, base_url: str, key: str, model: str, messages: list[dict], max_tokens: int):
    if kind not in KINDS:
        raise AIError(503, f"Provider type '{kind}' is not supported by this server.")
    return KINDS[kind].stream(base_url, key, model, messages, max_tokens)


def list_models(kind: str, base_url: str, key: str) -> list[str]:
    if kind not in KINDS:
        raise AIError(503, f"Provider type '{kind}' is not supported by this server.")
    return KINDS[kind].models(base_url, key)
