"""Ortam degiskenlerini yukler ve .env eksikse ne yapilacagini soyler.

Ayri bir modul olmasinin sebebi: her giris noktasi (main.py, get_chat_id.py)
ayni kontrolu yapmali ve bu kontrol `lingo.config` okunmadan once calismali -
config degerlerini import aninda hesapliyor.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IS_WINDOWS = sys.platform == "win32"
VENV_PYTHON = (
    PROJECT_ROOT / ".venv" / ("Scripts/python.exe" if _IS_WINDOWS else "bin/python")
)
_ACTIVATE = ".venv\Scripts\activate" if _IS_WINDOWS else "source .venv/bin/activate"


def _explain_missing_package(package: str) -> None:
    """Sanal ortam etkinlestirilmeden calistirildiginda ne yapilacagini soyler.

    Cikti ham ModuleNotFoundError olursa kullanici paketi global Python'a
    kurmaya calisiyor; asil sebep neredeyse her zaman etkinlestirilmemis .venv.
    """
    in_venv = sys.prefix != sys.base_prefix
    print()
    print(f"  Gerekli paket bulunamadi: {package}")
    print(f"  Kullanilan Python: {sys.executable}")
    print()
    if not in_venv and VENV_PYTHON.exists():
        print("  Sanal ortami etkinlestirmeyi unutmussun. Proje klasorunde:")
        print()
        print(f"      {_ACTIVATE}")
        print()
        print("  Etkinlesince komut satirinin basinda (.venv) gorunur.")
        print("  Etkinlestirmeden calistirmak istersen:")
        print()
        print(f"      {VENV_PYTHON} <script.py>")
    else:
        print("  Paketleri kur:")
        print()
        print("      python -m venv .venv")
        print(f"      {_ACTIVATE}")
        print("      pip install -r requirements.txt")
    print()
    sys.exit(1)


def check_dependencies() -> None:
    """Zorunlu paketleri kontrol eder.

    gTTS bilerek listede yok: sesi olmayan bir kart hala ise yarar, bu yuzden
    eksikligi calismayi durdurmaz - lingo.tts sessizce metne duser.
    """
    try:
        __import__("requests")
    except ImportError:
        _explain_missing_package("requests")


try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - yol kullaniciya mesaj basip cikiyor
    _explain_missing_package("python-dotenv")

ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


def _fix_console_encoding() -> None:
    """Windows konsolu varsayilan olarak cp1254 - emoji basarken cokuyor."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def load_env() -> bool:
    """`.env` dosyasini yukler. Dosya varsa True doner.

    Dosya yoksa da ortam degiskenleri gecerli olabilir - GitHub Actions
    boyle calisir, orada .env yoktur ve secret'lar env olarak gelir.
    """
    _fix_console_encoding()
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        return True
    load_dotenv()
    return False


def explain_missing_env() -> None:
    """`.env` yokken ne yapilacagini anlatir."""
    print()
    print("  .env dosyasi bulunamadi.")
    print(f"  Beklenen konum: {ENV_PATH}")
    if not ENV_EXAMPLE.exists():
        print("  UYARI: .env.example de yok - repo eksik indirilmis olabilir.")
    print()
    print("  Olusturmak icin proje klasorunde:")
    print()
    print("      copy .env.example .env")
    print("      notepad .env")
    print()
    print("  (GitHub Actions'ta .env gerekmez - secret'lar kullanilir.)")
    print()
