"""Saglayicidan bagimsiz LLM katmani.

Gunde bes cagri yapiyoruz (her gonderim slotunda bir tane). Gemini free
katmani dakikada 15 / gunde 1500 istek veriyor - fazlasiyla yetiyor.
Saglayici `LINGO_PROVIDER` ile secilir:

    gemini      Google AI Studio - ucretsiz, kredi karti istemiyor  (varsayilan)
    groq        Groq - ucretsiz, kredi karti istemiyor
    openrouter  OpenRouter - ":free" ekli modeller ucretsiz
    anthropic   Claude - ucretli, en iyi eleme kalitesi

Gemini, Groq ve OpenRouter icin SDK kurmuyoruz - ucu de basit REST API,
`requests` yetiyor. Bu bagimlilik sayisini ve surum kaymasi riskini dusuruyor.
"""
from __future__ import annotations

import os
import time

import requests

from . import config


class LLMError(RuntimeError):
    """LLM cagrisi basarisiz oldu. main.py bunu yakalayip sadece tekrar kartlarini gonderir."""


def _require_key(env_name: str, provider: str, url: str) -> str:
    key = os.getenv(env_name)
    if not key:
        raise LLMError(
            f"{env_name} tanimli degil ({provider} icin gerekli).\n"
            f"Ucretsiz anahtar: {url}\n"
            f"Anahtari .env dosyasina ekle."
        )
    return key


# Gecici sunucu hatalari. Ucretsiz katmanlarda 503 ("yogun talep") sik goruluyor
# ve genellikle birkac saniye sonra geciyor - tek denemede pes etmek, kaliteli
# ozet yerine ham listeye dusmek demek.
_RETRY_STATUSES = {500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (2, 6, 15)


def _post(url: str, *, json: dict, headers: dict | None = None, provider: str) -> dict:
    son_hata = ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = requests.post(url, json=json, headers=headers or {}, timeout=120)
        except requests.RequestException as exc:
            son_hata = f"{provider} baglanti hatasi: {type(exc).__name__}: {exc}"
            if attempt < _MAX_ATTEMPTS - 1:
                bekle = _BACKOFF_SECONDS[attempt]
                print(f"  {son_hata} - {bekle}s sonra tekrar deneniyor "
                      f"({attempt + 2}/{_MAX_ATTEMPTS})")
                time.sleep(bekle)
                continue
            raise LLMError(son_hata) from exc

        if resp.ok:
            try:
                return resp.json()
            except ValueError as exc:
                raise LLMError(f"{provider} JSON dondurmedi: {resp.text[:300]}") from exc

        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
            bekle = _BACKOFF_SECONDS[attempt]
            print(f"  {provider} HTTP {resp.status_code} (gecici) - {bekle}s sonra "
                  f"tekrar deneniyor ({attempt + 2}/{_MAX_ATTEMPTS})")
            time.sleep(bekle)
            continue

        raise LLMError(_hata_mesaji(provider, resp))

    raise LLMError(son_hata or f"{provider}: beklenmeyen durum")


def _hata_mesaji(provider: str, resp) -> str:
    """Duruma gore dogru tavsiyeyi veren hata metni.

    Her hataya "model adi yanlis olabilir" demek yaniltici - 503 gecici
    yogunluk, 429 kota, 404 gercekten yanlis model adi.
    """
    govde = resp.text[:400]
    if resp.status_code == 429:
        return (
            f"{provider} kota siniri (429). Ucretsiz katmanin limiti dolmus "
            f"olabilir; yarinki calistirmada sifirlanir.\n{govde}"
        )
    if resp.status_code in _RETRY_STATUSES:
        return (
            f"{provider} HTTP {resp.status_code}: sunucu gecici olarak yogun. "
            f"{_MAX_ATTEMPTS} deneme de basarisiz oldu.\n{govde}"
        )
    if resp.status_code in (400, 404):
        return (
            f"{provider} HTTP {resp.status_code}: {govde}\n"
            f"Model adi yanlis olabilir - 'python list_models.py' ile gecerli "
            f"adlari listeleyebilirsin."
        )
    if resp.status_code in (401, 403):
        return (
            f"{provider} HTTP {resp.status_code}: API anahtari gecersiz veya "
            f"yetkisiz.\n{govde}"
        )
    return f"{provider} HTTP {resp.status_code}: {govde}"


# --- Google Gemini ---------------------------------------------------------

def _complete_gemini(system: str, user: str) -> str:
    key = _require_key("GEMINI_API_KEY", "Gemini", "https://aistudio.google.com/apikey")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.LLM_MODEL}:generateContent"
    )
    payload = _post(
        url,
        headers={"x-goog-api-key": key},
        provider="Gemini",
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 4000,
                # JSON'u modelin iyi niyetine birakmak yerine API seviyesinde zorla.
                "responseMimeType": "application/json",
            },
        },
    )

    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = payload.get("promptFeedback", {}).get("blockReason")
        raise LLMError(f"Gemini bos yanit dondu (blockReason={blocked})")

    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        reason = candidates[0].get("finishReason")
        raise LLMError(f"Gemini metin dondurmedi (finishReason={reason})")

    usage = payload.get("usageMetadata", {})
    print(
        f"LLM (Gemini/{config.LLM_MODEL}): "
        f"{usage.get('promptTokenCount', '?')} girdi / "
        f"{usage.get('candidatesTokenCount', '?')} cikti token"
    )
    return text


# --- OpenAI uyumlu saglayicilar (Groq, OpenRouter) -------------------------

_OPENAI_COMPATIBLE = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env": "GROQ_API_KEY",
        "signup": "https://console.groq.com/keys",
        "label": "Groq",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env": "OPENROUTER_API_KEY",
        "signup": "https://openrouter.ai/keys",
        "label": "OpenRouter",
    },
}


def _complete_openai_compatible(provider: str, system: str, user: str) -> str:
    spec = _OPENAI_COMPATIBLE[provider]
    key = _require_key(spec["env"], spec["label"], spec["signup"])

    payload = _post(
        spec["url"],
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        provider=spec["label"],
        json={
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.9,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
        },
    )

    choices = payload.get("choices") or []
    if not choices:
        raise LLMError(f"{spec['label']} bos yanit dondu: {str(payload)[:300]}")
    text = (choices[0].get("message") or {}).get("content") or ""
    if not text.strip():
        raise LLMError(f"{spec['label']} metin dondurmedi")

    usage = payload.get("usage", {})
    print(
        f"LLM ({spec['label']}/{config.LLM_MODEL}): "
        f"{usage.get('prompt_tokens', '?')} girdi / "
        f"{usage.get('completion_tokens', '?')} cikti token"
    )
    return text


# --- Anthropic Claude ------------------------------------------------------

def _complete_anthropic(system: str, user: str) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError(
            "anthropic paketi kurulu degil. 'pip install anthropic' calistir "
            "veya ucretsiz bir saglayici sec (LINGO_PROVIDER=gemini)."
        ) from exc

    _require_key("ANTHROPIC_API_KEY", "Claude", "https://console.anthropic.com")
    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": config.EFFORT},
            system=[
                {
                    "type": "text",
                    "text": system,
                    # Sistem promptu sabit; prompt cache prefix eslesmesi yapiyor.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as exc:
        raise LLMError(f"Claude API hatasi: {exc}") from exc

    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "")
        raise LLMError(f"Claude istegi reddetti: {detail}")

    text = "".join(b.text for b in response.content if b.type == "text")
    if not text.strip():
        raise LLMError("Claude bos yanit dondu")

    usage = response.usage
    print(
        f"LLM (Claude/{config.LLM_MODEL}): {usage.input_tokens} girdi / "
        f"{usage.output_tokens} cikti token "
        f"(cache okuma: {getattr(usage, 'cache_read_input_tokens', 0)})"
    )
    return text


# --- Genel giris noktasi ---------------------------------------------------

def complete(system: str, user: str) -> str:
    """Secili saglayiciya tek bir istek atar ve ham metin yanitini dondurur."""
    provider = config.LLM_PROVIDER
    if provider == "gemini":
        return _complete_gemini(system, user)
    if provider in _OPENAI_COMPATIBLE:
        return _complete_openai_compatible(provider, system, user)
    if provider == "anthropic":
        return _complete_anthropic(system, user)
    raise LLMError(
        f"Bilinmeyen saglayici: {provider!r}. "
        f"Gecerli secenekler: gemini, groq, openrouter, anthropic"
    )
