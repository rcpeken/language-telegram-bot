"""Saglayicilarda kullanilabilir model adlarini listeler.

Model adlari zamanla degisir ve yanlis ad HTTP 404 olarak geri doner.
Elindeki anahtarla hangi modellere erisebildigini gormek icin:

    python list_models.py            # anahtari olan tum saglayicilar
    python list_models.py gemini     # tek saglayici
"""
from __future__ import annotations

import os
import sys

import requests

from lingo.bootstrap import load_env

load_env()


def list_gemini() -> None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("  GEMINI_API_KEY yok - atlaniyor (ucretsiz: https://aistudio.google.com/apikey)")
        return
    resp = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        params={"pageSize": 100},
        timeout=30,
    )
    if not resp.ok:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return
    for model in resp.json().get("models", []):
        name = model.get("name", "").removeprefix("models/")
        # Sadece metin uretebilen modeller ise yarar.
        if "generateContent" not in model.get("supportedGenerationMethods", []):
            continue
        if "embedding" in name or "aqa" in name:
            continue
        print(f"  {name:<45} {model.get('displayName', '')}")


def list_groq() -> None:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        print("  GROQ_API_KEY yok - atlaniyor (ucretsiz: https://console.groq.com/keys)")
        return
    resp = requests.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
    if not resp.ok:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return
    for model in sorted(resp.json().get("data", []), key=lambda m: m.get("id", "")):
        if "whisper" in model.get("id", "") or "tts" in model.get("id", ""):
            continue
        ctx = model.get("context_window", "?")
        print(f"  {model.get('id', ''):<45} baglam: {ctx}")


def list_openrouter() -> None:
    # OpenRouter model listesi anahtarsiz da okunabiliyor.
    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    if not resp.ok:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return
    free = [m for m in resp.json().get("data", []) if m.get("id", "").endswith(":free")]
    if not free:
        print("  Ucretsiz model bulunamadi.")
        return
    for model in sorted(free, key=lambda m: m.get("id", "")):
        ctx = model.get("context_length", "?")
        print(f"  {model.get('id', ''):<45} baglam: {ctx}")


def list_anthropic() -> None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        print("  ANTHROPIC_API_KEY yok - atlaniyor (ucretli: https://console.anthropic.com)")
        return
    resp = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout=30,
    )
    if not resp.ok:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return
    for model in resp.json().get("data", []):
        print(f"  {model.get('id', ''):<45} {model.get('display_name', '')}")


PROVIDERS = {
    "gemini": ("Google Gemini (ucretsiz katman)", list_gemini),
    "groq": ("Groq (ucretsiz katman)", list_groq),
    "openrouter": ("OpenRouter (:free modeller)", list_openrouter),
    "anthropic": ("Anthropic Claude (ucretli)", list_anthropic),
}


def main() -> int:
    wanted = sys.argv[1:] or list(PROVIDERS)
    for name in wanted:
        if name not in PROVIDERS:
            print(f"Bilinmeyen saglayici: {name}. Secenekler: {', '.join(PROVIDERS)}")
            return 1
        label, fn = PROVIDERS[name]
        print(f"\n{label}\n" + "-" * 70)
        try:
            fn()
        except Exception as exc:
            print(f"  HATA {type(exc).__name__}: {exc}")

    print("\nSectigin adi .env icine yaz: LINGO_MODEL=<model-adi>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
