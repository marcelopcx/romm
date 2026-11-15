"""Machine translation of achievement texts, cached on disk.

RetroAchievements publishes titles and descriptions in English only. When
``ACHIEVEMENTS_LANGUAGE`` is set, texts already in the cache are swapped in right
away; the rest are translated in the background (one text at a time, Google
Translate's keyless endpoint) and show up on the next request.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from config import ROMM_BASE_PATH
from logger.logger import log
from utils.context import ctx_httpx_client

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
CACHE_DIR = Path(ROMM_BASE_PATH) / "config"
# Achievements with this id prefix already carry the console's own language.
_SKIP_PREFIXES = ("vita-",)
_SAVE_EVERY = 25
_PAUSE = 0.15  # seconds between requests, to stay polite with the free endpoint

_caches: dict[str, dict[str, str]] = {}
_task: asyncio.Task[None] | None = None


def _cache_path(lang: str) -> Path:
    return CACHE_DIR / f"achievement-translations-{lang}.json"


def _load(lang: str) -> dict[str, str]:
    if lang not in _caches:
        try:
            data = json.loads(_cache_path(lang).read_text(encoding="utf-8"))
            _caches[lang] = (
                {k: v for k, v in data.items() if isinstance(v, str)}
                if isinstance(data, dict)
                else {}
            )
        except FileNotFoundError:
            _caches[lang] = {}
        except (OSError, ValueError):
            log.exception("Could not read achievement translations")
            _caches[lang] = {}
    return _caches[lang]


def _save(lang: str) -> None:
    path = _cache_path(lang)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(_caches.get(lang, {}), ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError:
        log.exception("Could not save achievement translations")


async def _translate(text: str, lang: str) -> str | None:
    """One text through Google Translate; None when the request fails."""
    response = await ctx_httpx_client.get().get(
        TRANSLATE_URL,
        params={"client": "gtx", "sl": "en", "tl": lang, "dt": "t", "q": text},
        timeout=15,
    )
    response.raise_for_status()
    segments = response.json()[0]
    translated = "".join(seg[0] for seg in segments if seg and seg[0])
    return translated.strip() or None


async def _fill(texts: list[str], lang: str) -> None:
    cache = _load(lang)
    done = 0
    for text in texts:
        if text in cache:
            continue
        try:
            translated = await _translate(text, lang)
        except Exception:
            log.warning("Achievement translation stopped; it will retry later")
            break
        if translated:
            cache[text] = translated
            done += 1
            if done % _SAVE_EVERY == 0:
                _save(lang)
        await asyncio.sleep(_PAUSE)
    if done:
        _save(lang)
        log.info(f"Translated {done} achievement texts to '{lang}'")


def _schedule(texts: set[str], lang: str) -> None:
    global _task
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _task = loop.create_task(_fill(sorted(texts), lang))


def translate_overview(overview: dict[str, Any], lang: str) -> dict[str, Any]:
    """Swap cached translations into the overview; queue the rest in the background."""
    if not lang or lang == "en":
        return overview
    cache = _load(lang)
    missing: set[str] = set()
    for game in overview.get("games", []):
        for achievement in game.get("achievements", []):
            if str(achievement.get("id", "")).startswith(_SKIP_PREFIXES):
                continue
            for key in ("title", "description"):
                text = achievement.get(key)
                if not text:
                    continue
                translated = cache.get(text)
                if translated:
                    achievement[key] = translated
                else:
                    missing.add(text)
    if missing:
        _schedule(missing, lang)
    return overview
