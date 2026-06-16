"""Real-time news headlines for grounding AI price analysis - NO guessing.

Fetches genuine, recent news from Google News RSS (free, no API key) about the
commodity behind a tracked food item, so the AI analyst reasons from REAL
current events (export bans, weather damage, fuel changes, festival demand)
instead of hallucinating. Every headline carries its real source, date and URL.

The food name is mapped to an English commodity keyword (+ its import origin
country, reused from analytics.drivers) to get focused, relevant results.

Headlines are cached briefly (data/news/*.json, ~6h) so repeated analysis is
fast and doesn't hammer the feed, while staying genuinely "today's news".
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

from src.analytics.drivers import detect_origin

CACHE = Path("data/news")
CACHE.mkdir(parents=True, exist_ok=True)
CACHE_AGE_HOURS = 6
UA = {"User-Agent": "Mozilla/5.0 FoodPriceTracker"}

# Only news this recent is relevant for forecasting the next month or two.
# 120 days back from mid-2026 excludes all 2025-and-earlier articles, which is
# exactly the "why is it citing 2024 news" problem. Google News also gets a
# `when:` operator so it returns recent results server-side.
MAX_AGE_DAYS = 120

# Map a tracked food to an English commodity search term. Matched as a
# lower-cased substring of the food name; first hit wins, so list the more
# specific names first (garlic before the generic onion fallback).
COMMODITY_KEYWORDS = [
    ("bawang putih", "garlic"),
    ("garlic", "garlic"),
    ("bawang merah", "onion"),
    ("bawang kecil", "onion"),
    ("bawang besar", "onion"),
    ("bawang", "onion"),
    ("onion", "onion"),
    ("ubi kentang", "potato"),
    ("potato", "potato"),
    ("cooking oil", "palm oil"),
    ("palm", "palm oil"),
    ("minyak", "palm oil"),
    ("beras", "rice"),
    ("rice", "rice"),
    ("ayam", "chicken"),
    ("chicken", "chicken"),
    ("telur", "egg"),
    ("egg", "egg"),
    ("gula", "sugar"),
    ("sugar", "sugar"),
    ("tepung", "wheat flour"),
    ("flour", "wheat flour"),
    ("ikan", "fish"),
    ("fish", "fish"),
    ("tomato", "tomato"),
    ("susu", "milk"),
    ("milk", "milk"),
    ("cili", "chili"),
    ("sayur", "vegetable"),
    ("kubis", "cabbage"),
    ("pisang", "banana"),
]


def commodity_for(food_name: str) -> str:
    """Best English commodity keyword for a food name (fallback: the name itself)."""
    low = food_name.lower()
    for needle, term in COMMODITY_KEYWORDS:
        if needle in low:
            return term
    # Fallback: strip parentheticals / "import" and use the leading words.
    cleaned = re.sub(r"\(.*?\)|import|holland|rose|biasa", " ", low)
    return " ".join(cleaned.split()[:2]) or food_name


def build_queries(food_name: str) -> list:
    """Two focused Google News queries: global supply/price + Malaysia price."""
    commodity = commodity_for(food_name)
    origin = detect_origin(food_name)  # e.g. 'INDIA', 'CHINA', or None
    origin_word = origin.title() if origin and origin != "IMPORT" else ""

    # Lead with the commodity so results stay on-topic; origin/Malaysia add context.
    global_q = f"{commodity} price {origin_word} export".strip()
    local_q = f"{commodity} price Malaysia"
    # De-dupe if origin made them identical-ish
    queries = [global_q, local_q]
    return [q for i, q in enumerate(queries) if q and q not in queries[:i]]


def _parse_rss(xml_text: str) -> list:
    """Parse ALL Google News RSS items into [{title, source, date, link}].

    `date` is YYYY-MM-DD when the pubDate parses, else None (date filtering
    happens in fetch_news so an unverifiable date can be dropped, not trusted).
    Parses everything (no early cap) so the caller can filter by recency first.
    """
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text
                  else "")
        date_str = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                date_str = datetime.strptime(pub, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if title:
            items.append({"title": title, "source": source,
                          "date": date_str, "link": link})
    return items


def _fetch_query(query: str, days: int = MAX_AGE_DAYS) -> list:
    # `when:Nd` asks Google News for results from the last N days only.
    q = f"{query} when:{days}d"
    url = ("https://news.google.com/rss/search?q="
           f"{quote_plus(q)}&hl=en-MY&gl=MY&ceid=MY:en")
    r = requests.get(url, timeout=20, headers=UA)
    r.raise_for_status()
    return _parse_rss(r.text)


def fetch_news(food_name: str, per_query: int = 6, total: int = 8) -> dict:
    """Fetch recent real headlines about the commodity behind `food_name`.

    Returns {"queries": [...], "headlines": [{title, source, date, link}],
    "fetched_at": iso, "error": optional}. Cached ~6h per food.
    """
    safe = re.sub(r"[^a-z0-9]+", "_", food_name.lower()).strip("_")
    path = CACHE / f"{safe}.json"

    if path.exists():
        age_h = (datetime.now()
                 - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
        if age_h < CACHE_AGE_HOURS:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    queries = build_queries(food_name)
    cutoff = (datetime.now() - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    # On-topic guard: the headline must mention the commodity (a word >=3 chars
    # of it), so generic "India business" / "oil price" noise is dropped.
    commodity = commodity_for(food_name)
    topic_words = [w for w in commodity.lower().split() if len(w) >= 3]
    headlines, seen = [], set()
    error = None
    try:
        for q in queries:
            for h in _fetch_query(q):
                key = h["title"].lower()
                if key in seen:
                    continue
                # Drop anything we can't date, or that is older than the window
                # (the whole point: no 2024/2025 articles for a 2026 forecast).
                if not h.get("date") or h["date"] < cutoff:
                    continue
                # Drop off-topic results (must mention the commodity).
                if topic_words and not any(w in key for w in topic_words):
                    continue
                seen.add(key)
                headlines.append(h)
    except requests.RequestException as e:
        error = f"news fetch failed: {e}"

    # Newest first; cap to `total`.
    headlines.sort(key=lambda h: h["date"], reverse=True)
    headlines = headlines[:total]

    result = {"queries": queries, "headlines": headlines,
              "fetched_at": datetime.now().isoformat(timespec="seconds")}
    if error:
        result["error"] = error
    if headlines:  # only cache a useful result
        try:
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError:
            pass
    return result
