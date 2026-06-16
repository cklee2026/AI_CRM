"""Optional AI-powered analysis (off by default).

The customer enters their own API key in the dashboard Settings page.
Providers: DeepSeek (default) or any OpenAI-compatible endpoint
(Zhipu GLM, Moonshot, local Ollama, etc.) - the model name is free text,
so new models work without code changes.

Budget protection: when the provider reports the balance/quota is
exhausted (HTTP 402 / "insufficient balance"), AI analysis is
AUTOMATICALLY DISABLED and the reason is shown in the dashboard until
the customer tops up and re-enables it.

Settings are stored in data/ai_settings.json (travels with the portable
folder; keep the folder private since it contains the API key).
"""
import json
import requests
from datetime import datetime
from pathlib import Path

SETTINGS_FILE = Path("./data/ai_settings.json")

PROVIDERS = {
    # Per https://api-docs.deepseek.com (checked 2026-06): current models are
    # deepseek-v4-flash and deepseek-v4-pro; deepseek-chat / deepseek-reasoner
    # are deprecated as of 2026-07-24. Error 402 = insufficient balance.
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
    },
    "Custom (OpenAI-compatible)": {
        "base_url": "",
        "default_model": "",
    },
}

# Old DeepSeek model names -> current replacements (deprecation 2026-07-24)
MODEL_MIGRATIONS = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}

DEFAULT_SETTINGS = {
    "enabled": False,
    "provider": "DeepSeek",
    "base_url": PROVIDERS["DeepSeek"]["base_url"],
    "model": PROVIDERS["DeepSeek"]["default_model"],
    "api_key": "",
    "total_tokens_used": 0,
    "last_used": None,
    "disabled_reason": None,
    "disabled_at": None,
}


class AIError(Exception):
    """kind: 'budget' | 'auth' | 'rate_limit' | 'disabled' | 'other'"""
    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------
# API key protection (Windows DPAPI)
#
# On Windows the key is encrypted with CryptProtectData, bound to the current
# Windows user account: the settings file never contains the plaintext key,
# and the encrypted blob CANNOT be decrypted on another computer or by
# another user. (Consequence: after copying the folder to a new PC, re-enter
# the key once in AI Settings.) On other OSes the key is stored as-is.
# ---------------------------------------------------------------------------
import sys
import base64

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob_to_bytes(blob) -> bytes:
        data = ctypes.string_at(blob.pbData, blob.cbData)
        ctypes.windll.kernel32.LocalFree(blob.pbData)
        return data

    def _protect_key(plaintext: str) -> str:
        """Encrypt with DPAPI; returns base64 blob ('' if input empty)."""
        if not plaintext:
            return ""
        raw = plaintext.encode("utf-8")
        blob_in = _DATA_BLOB(len(raw), ctypes.cast(
            ctypes.create_string_buffer(raw, len(raw)),
            ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)):
            return ""  # encryption unavailable - caller falls back
        return base64.b64encode(_blob_to_bytes(blob_out)).decode("ascii")

    def _unprotect_key(b64_blob: str) -> str:
        """Decrypt a DPAPI blob; '' if it cannot be decrypted (other PC/user)."""
        if not b64_blob:
            return ""
        try:
            raw = base64.b64decode(b64_blob)
        except (ValueError, TypeError):
            return ""
        blob_in = _DATA_BLOB(len(raw), ctypes.cast(
            ctypes.create_string_buffer(raw, len(raw)),
            ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)):
            return ""
        return _blob_to_bytes(blob_out).decode("utf-8", errors="replace")
else:
    def _protect_key(plaintext: str) -> str:
        return ""

    def _unprotect_key(b64_blob: str) -> str:
        return ""


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass

    # Decrypt the protected key for in-memory use (never re-written as plaintext)
    protected = settings.pop("api_key_protected", "")
    if protected and not settings.get("api_key"):
        settings["api_key"] = _unprotect_key(protected)

    # Migrate deprecated DeepSeek model names (removed 2026-07-24)
    if settings.get("model") in MODEL_MIGRATIONS:
        settings["model"] = MODEL_MIGRATIONS[settings["model"]]

    return settings


def save_settings(settings: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    on_disk = dict(settings)

    # Never write the plaintext key on Windows - store the DPAPI blob instead
    plaintext = on_disk.get("api_key", "")
    if sys.platform == "win32" and plaintext:
        protected = _protect_key(plaintext)
        if protected:
            on_disk["api_key_protected"] = protected
            on_disk["api_key"] = ""

    SETTINGS_FILE.write_text(
        json.dumps(on_disk, indent=2, ensure_ascii=False), encoding="utf-8")


def _classify_error(status_code: int, body: str) -> str:
    text = (body or "").lower()
    if status_code == 402 or "insufficient balance" in text or "quota" in text:
        return "budget"
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        # Some providers use 429 for exhausted quota too
        if "quota" in text or "balance" in text:
            return "budget"
        return "rate_limit"
    return "other"


def _auto_disable(settings: dict, reason: str):
    settings["enabled"] = False
    settings["disabled_reason"] = reason
    settings["disabled_at"] = datetime.now().isoformat(timespec="seconds")
    save_settings(settings)


def chat(messages: list, settings: dict = None, max_tokens: int = 1000) -> str:
    """Call the configured chat-completions API. Returns the reply text.

    Raises AIError; on budget exhaustion the AI feature is auto-disabled.
    """
    s = settings or load_settings()
    if not s["enabled"]:
        raise AIError("AI analysis is turned off (enable it in Settings).",
                      kind="disabled")
    if not s["api_key"] or not s["base_url"] or not s["model"]:
        raise AIError("AI settings incomplete: need API key, base URL and model.",
                      kind="auth")

    try:
        resp = requests.post(
            f"{s['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {s['api_key']}",
                     "Content-Type": "application/json"},
            json={"model": s["model"], "messages": messages,
                  "max_tokens": max_tokens, "temperature": 0.3,
                  "stream": False},
            timeout=90,
        )
    except requests.RequestException as e:
        raise AIError(f"Could not reach the AI provider: {e}", kind="other")

    if resp.status_code != 200:
        kind = _classify_error(resp.status_code, resp.text)
        if kind == "budget":
            _auto_disable(s, "API balance/token quota exhausted "
                             "(provider returned: insufficient balance). "
                             "Top up your account, then re-enable AI in Settings.")
            raise AIError(
                "AI tokens/balance exhausted - AI analysis has been "
                "AUTOMATICALLY TURNED OFF. Top up and re-enable in Settings.",
                kind="budget")
        if kind == "auth":
            raise AIError("API key rejected (401/403). Check the key in Settings.",
                          kind="auth")
        if kind == "rate_limit":
            raise AIError("Rate limited (429). Wait a minute and try again.",
                          kind="rate_limit")
        raise AIError(f"AI provider error {resp.status_code}: {resp.text[:300]}",
                      kind="other")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AIError(f"Unexpected API response: {str(data)[:300]}", kind="other")

    usage = data.get("usage", {})
    s["total_tokens_used"] = int(s.get("total_tokens_used", 0)) + \
        int(usage.get("total_tokens", 0))
    s["last_used"] = datetime.now().isoformat(timespec="seconds")
    save_settings(s)
    return content


def test_connection(settings: dict) -> tuple:
    """Quick test call. Returns (ok: bool, message: str)."""
    probe = dict(settings)
    probe["enabled"] = True
    try:
        reply = chat([{"role": "user", "content": "Reply with the single word: OK"}],
                     settings=probe, max_tokens=64)
        return True, f"Connection OK - model replied: {reply.strip()[:60]}"
    except AIError as e:
        return False, str(e)


def generate_forecast_analysis(food: str, location: str,
                               result: dict, lang: str = "zh") -> str:
    """Ask the AI for a market analysis of a forecast result, GROUNDED in
    real-time news headlines (Google News) about the commodity.

    `result` is the dict from forecast_prices(). The prompt contains only
    real computed numbers PLUS genuinely-fetched recent headlines; the AI is
    told to base real-world reasoning ONLY on those headlines (with source +
    date), never to invent events, and to say so when news is missing.
    """
    hist = result["history"].tail(16)
    fc = result["forecast"]
    meta = result["meta"]
    facts = "\n".join(f"- {r['en']}" for r in result.get("explanations", []))

    # Real Malaysian festival/seasonal calendar facts (dates to watch), so the
    # AI accounts for the actual calendar instead of guessing about festivals.
    try:
        from src.analytics.calendar_alerts import price_calendar_alerts
        cal = price_calendar_alerts(food, location)
        if cal:
            facts += "\n" + "\n".join(f"- {a['en']}" for a in cal)
    except Exception:
        pass

    hist_lines = "\n".join(
        f"{str(row['date'])[:10]}: {row['price']:.2f}"
        for _, row in hist.iterrows())
    fc_lines = "\n".join(
        f"{str(row['date'])[:10]}: forecast {row['forecast']:.2f} "
        f"(95% range {row['lo']:.2f}-{row['hi']:.2f})"
        for _, row in fc.iterrows())

    # --- Real-time news grounding ---
    try:
        from src.analytics.news import fetch_news
        news = fetch_news(food)
    except Exception as e:
        news = {"headlines": [], "error": str(e)}

    if news.get("headlines"):
        news_block = "\n".join(
            f"- [{h['date']}] \"{h['title']}\" ({h['source'] or 'source'}) {h['link']}"
            for h in news["headlines"])
        news_instruction = (
            "Use ONLY the headlines above for real-world events. Cite the source "
            "and date in-line for any event you mention (e.g. \"per The Edge, "
            "2026-06-15\"). If a headline isn't clearly relevant, ignore it. Do "
            "NOT invent or recall any event, export ban, or weather story that is "
            "not in this list.")
    else:
        news_block = "(No news headlines could be fetched right now.)"
        news_instruction = (
            "No live news was available. Do NOT invent or recall any specific "
            "current event; say plainly that no recent news was found and keep "
            "the real-world section to general, clearly-labelled seasonal context.")

    lang_instruction = ("Respond in Simplified Chinese (简体中文)."
                        if lang == "zh" else "Respond in English.")

    prompt = f"""You are a food price analyst for a grocery price tracker in Sabah, Malaysia.

Item: {food}
Location: {location}
Forecast method: {meta['method']}

Recent price history (weekly/monthly averages, MYR):
{hist_lines}

Statistical forecast:
{fc_lines}

Computed statistical facts:
{facts}

REAL-TIME NEWS HEADLINES (fetched today from Google News - these are the ONLY
real-world events you may cite):
{news_block}

{news_instruction}

Write a concise market analysis (max ~320 words) for a shop owner:
1. Interpret the forecast in plain language - what should they expect and do?
2. Real-world drivers: explain which of the headlines above actually bear on
   this item's price (supply/export, weather, fuel, policy, festivals) and how.
   Cite source + date for each. If none are relevant, say so.
3. One practical recommendation (e.g. stock up now vs wait), tied to the above.
Do NOT invent any numbers beyond those given, and do NOT invent any news/events
beyond the headlines listed. {lang_instruction}"""

    return chat([{"role": "user", "content": prompt}], max_tokens=1200)
