"""Tips for a game, gathered from open sources and cached on disk.

* Wikipedia: the summary and the gameplay/story sections, in the UI language.
* libretro-database: cheat codes (GameShark, Game Genie, ...) with descriptions.
* StrategyWiki: guide pages (controls, characters, levels...).

Everything is fetched as plain text and shown inside RomM; nothing remote is
served as HTML. Descriptions and guide text that arrive in English are
translated to the UI language and cached, like the achievement texts.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import ROMM_BASE_PATH
from handler.metadata.achievement_translation import translate_now
from logger.logger import log
from utils.context import ctx_httpx_client

CACHE_DIR = Path(ROMM_BASE_PATH) / "config" / "game-tips"
CACHE_TTL = 30 * 86400
_HEADERS = {"User-Agent": "RomM-tips/1.0 (self-hosted game library)"}
_TIMEOUT = 15

_MAX_SUMMARY = 1000
_MAX_SECTION = 1800
_MAX_GUIDE_PAGES = 12
_MAX_GUIDE_TEXT = 1200
_MAX_CHEATS = 300
_MAX_TRANSLATED_CHEATS = 200

# RomM platform fs_slug -> folder under libretro-database/cht
CHEAT_DIRS: dict[str, str] = {
    "nes": "Nintendo - Nintendo Entertainment System",
    "famicom": "Nintendo - Nintendo Entertainment System",
    "snes": "Nintendo - Super Nintendo Entertainment System",
    "sfam": "Nintendo - Super Nintendo Entertainment System",
    "gb": "Nintendo - Game Boy",
    "gbc": "Nintendo - Game Boy Color",
    "gba": "Nintendo - Game Boy Advance",
    "n64": "Nintendo - Nintendo 64",
    "nds": "Nintendo - Nintendo DS",
    "psx": "Sony - PlayStation",
    "psp": "Sony - PlayStation Portable",
    "genesis": "Sega - Mega Drive - Genesis",
    "megadrive": "Sega - Mega Drive - Genesis",
    "sms": "Sega - Master System - Mark III",
    "gamegear": "Sega - Game Gear",
    "saturn": "Sega - Saturn",
    "segacd": "Sega - Mega-CD - Sega CD",
    "tg16": "NEC - PC Engine - TurboGrafx 16",
}
_DEVICES = (
    "Code Breaker",
    "GameShark",
    "Game Genie",
    "Action Replay",
    "Game Buster",
    "Pro Action Replay",
    "Cheat Device",
)
_REGIONS = ("USA", "Europe", "Japan", "World")
_CHT_BASE = "https://raw.githubusercontent.com/libretro/libretro-database/master/cht/"

_WIKI_SECTIONS = re.compile(
    r"gameplay|jugabilidad|sistema de juego|modo de juego|mec[aá]nica|"
    r"historia|argumento|trama|premisa|story|plot|spieler|jouabilit|"
    r"sinopsis|synopsis",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)))


def _strip_parens(title: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", title).strip()


async def _get(url: str, params: dict[str, Any] | None = None) -> Any | None:
    try:
        response = await ctx_httpx_client.get().get(
            url, params=params, headers=_HEADERS, timeout=_TIMEOUT
        )
        if response.status_code != 200:
            return None
        return response
    except Exception:
        return None


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    response = await _get(url, params)
    if response is None:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


# --- Wikipedia ---------------------------------------------------------------


def _wiki_sections(extract: str) -> tuple[str, list[dict[str, str]]]:
    parts = re.split(r"\n==+ *(.+?) *==+\n", "\n" + extract)
    summary = parts[0].strip()
    sections = []
    for title, body in zip(parts[1::2], parts[2::2]):
        body = re.sub(r"\n==+ .+? ==+\n", "\n", body).strip()
        if _WIKI_SECTIONS.search(title) and len(body) > 80:
            sections.append({"title": title.strip(), "text": _clip(body, _MAX_SECTION)})
    return summary, sections


async def _wikipedia(name: str, language: str) -> dict[str, Any] | None:
    api = f"https://{language}.wikipedia.org/w/api.php"
    found = await _get_json(
        api,
        {"action": "query", "list": "search", "srsearch": name, "srlimit": 6, "format": "json"},
    )
    titles = [r["title"] for r in (found or {}).get("query", {}).get("search", [])]
    wanted = _norm(name)
    title = next((t for t in titles if _norm(_strip_parens(t)) == wanted), None)
    if title is None:
        return None
    page = await _get_json(
        api,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
            "format": "json",
        },
    )
    pages = list(((page or {}).get("query") or {}).get("pages", {}).values())
    extract = pages[0].get("extract", "") if pages else ""
    if len(extract) < 120:
        return None
    summary, sections = _wiki_sections(extract)
    return {
        "title": title,
        "language": language,
        "summary": _clip(summary, _MAX_SUMMARY),
        "sections": sections,
    }


# --- libretro cheats ---------------------------------------------------------

_CHEAT_DESC = re.compile(r'^cheat(\d+)_desc\s*=\s*"(.*)"\s*$', re.MULTILINE)
_CHEAT_CODE = re.compile(r'^cheat(\d+)_code\s*=\s*"(.*)"\s*$', re.MULTILINE)


def parse_cht(text: str) -> list[dict[str, str]]:
    codes = {int(i): c for i, c in _CHEAT_CODE.findall(text)}
    entries = []
    for index, desc in sorted((int(i), d) for i, d in _CHEAT_DESC.findall(text)):
        code = codes.get(index, "").strip()
        if desc.strip() and code:
            entries.append({"description": desc.strip(), "code": code})
    return entries


def _cht_candidates(rom: dict[str, Any]) -> list[tuple[str, str]]:
    """(device, file name) pairs to try, following No-Intro naming."""
    bases = []
    for base in (rom.get("fs_name_no_ext"), rom.get("fs_name_no_tags")):
        if base and base not in bases:
            bases.append(base)
    names: list[str] = []
    for base in bases:
        if "(" in base:
            names.append(base)
        else:
            names.extend(f"{base} ({region})" for region in _REGIONS)
    out = []
    for name in names:
        for device in _DEVICES:
            out.append((device, f"{name} ({device}).cht"))
        out.append(("", f"{name}.cht"))
    return out


async def _cheats(rom: dict[str, Any]) -> list[dict[str, Any]]:
    folder = CHEAT_DIRS.get(rom.get("platform_fs_slug") or "")
    if not folder:
        return []
    semaphore = asyncio.Semaphore(8)

    async def fetch(device: str, filename: str):
        async with semaphore:
            response = await _get(_CHT_BASE + quote(folder) + "/" + quote(filename))
        return device, (response.text if response is not None else None)

    results = await asyncio.gather(*(fetch(d, f) for d, f in _cht_candidates(rom)))
    groups: list[dict[str, Any]] = []
    for device, text in results:
        if not text:
            continue
        entries = parse_cht(text)
        if entries:
            groups.append({"device": device or "Cheats", "entries": entries[:_MAX_CHEATS]})
    return groups


# --- StrategyWiki ------------------------------------------------------------

_SW_API = "https://strategywiki.org/w/api.php"


async def _strategywiki(name: str) -> dict[str, Any] | None:
    found = await _get_json(
        _SW_API,
        {"action": "query", "list": "search", "srsearch": name, "srnamespace": 0, "srlimit": 6, "format": "json"},
    )
    titles = [r["title"] for r in (found or {}).get("query", {}).get("search", [])]
    wanted = _norm(name)
    title = next((t for t in titles if _norm(_strip_parens(t.split("/")[0])) == wanted), None)
    if title is None:
        return None
    title = title.split("/")[0]
    data = await _get_json(
        _SW_API,
        {
            "action": "query",
            "generator": "allpages",
            "gapprefix": f"{title}/",
            "gaplimit": 40,
            "gapnamespace": 0,
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "exlimit": "max",
            "format": "json",
        },
    )
    pages = []
    for page in ((data or {}).get("query") or {}).get("pages", {}).values():
        text = (page.get("extract") or "").strip()
        sub = page.get("title", "").split("/", 1)[-1]
        if len(text) < 80 or sub.lower().startswith("table of contents"):
            continue
        pages.append({"index": page.get("index", 0), "title": sub, "text": _clip(text, _MAX_GUIDE_TEXT)})
    pages.sort(key=lambda p: p["index"])
    pages = [{"title": p["title"], "text": p["text"]} for p in pages[:_MAX_GUIDE_PAGES]]
    return {"title": title, "pages": pages} if pages else None


# --- orchestration -----------------------------------------------------------


def _cache_file(rom_id: int, lang: str) -> Path:
    return CACHE_DIR / f"{rom_id}-{lang or 'en'}.json"


def _read_cache(rom_id: int, lang: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_cache_file(rom_id, lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or time.time() - data.get("fetched_at", 0) > CACHE_TTL:
        return None
    return data.get("tips")


def _write_cache(rom_id: int, lang: str, tips: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(rom_id, lang).write_text(
            json.dumps({"fetched_at": time.time(), "tips": tips}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        log.exception("Could not cache game tips")


async def _translate_tips(tips: dict[str, Any], lang: str) -> None:
    """English cheat descriptions and guide text -> the UI language, in place."""
    if not lang:
        return
    texts: list[str] = []
    for group in tips["cheats"]:
        texts.extend(e["description"] for e in group["entries"][:_MAX_TRANSLATED_CHEATS])
    guide = tips.get("guide")
    if guide:
        for page in guide["pages"]:
            texts.extend((page["title"], page["text"]))
    wiki = tips.get("wikipedia")
    if wiki and wiki["language"] != lang:  # fell back to English
        texts.extend((wiki["summary"], *(s["title"] for s in wiki["sections"]), *(s["text"] for s in wiki["sections"])))
    if not texts:
        return
    done = await translate_now(texts, lang)
    for group in tips["cheats"]:
        for entry in group["entries"][:_MAX_TRANSLATED_CHEATS]:
            entry["description"] = done.get(entry["description"], entry["description"])
    if guide:
        for page in guide["pages"]:
            page["title"] = done.get(page["title"], page["title"])
            page["text"] = done.get(page["text"], page["text"])
    if wiki and wiki["language"] != lang:
        wiki["summary"] = done.get(wiki["summary"], wiki["summary"])
        for s in wiki["sections"]:
            s["title"] = done.get(s["title"], s["title"])
            s["text"] = done.get(s["text"], s["text"])


async def get_tips(rom: dict[str, Any], lang: str) -> dict[str, Any]:
    """Tips for one ROM. ``lang`` is a translator code ("es"), or "" to keep English."""
    cached = _read_cache(rom["id"], lang)
    if cached is not None:
        return cached
    name = rom.get("name") or rom.get("fs_name_no_tags") or rom.get("fs_name_no_ext") or ""
    name = _strip_parens(name).strip()
    wiki_langs = [lang, "en"] if lang and lang != "en" else ["en"]

    async def wiki() -> dict[str, Any] | None:
        for language in wiki_langs:
            result = await _wikipedia(name, language)
            if result:
                return result
        return None

    wikipedia, cheats, guide = await asyncio.gather(
        wiki(), _cheats(rom), _strategywiki(name)
    )
    tips: dict[str, Any] = {"wikipedia": wikipedia, "cheats": cheats, "guide": guide}
    await _translate_tips(tips, lang)
    # Nothing found is cached too, but only for a day: sources fill in over time.
    if wikipedia or cheats or guide:
        _write_cache(rom["id"], lang, tips)
    return tips
