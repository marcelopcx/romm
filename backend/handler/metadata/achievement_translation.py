"""Machine translation of achievement texts, cached on disk.

RetroAchievements publishes titles and descriptions in English only. The client
sends its UI language; texts already in the cache are swapped in right away, the
rest are translated in the background (one text at a time, Google Translate's
keyless endpoint) and show up on the next request.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2

from config import ROMM_BASE_PATH
from logger.logger import log
from utils.context import ctx_httpx_client

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
CACHE_DIR = Path(ROMM_BASE_PATH) / "config"
# Achievements with this id prefix already carry the console's own language.
_SKIP_PREFIXES = ("vita-",)
_SAVE_EVERY = 25
_PAUSE = 0.7  # seconds between requests: the free endpoint throttles bursts
_BACKOFF_START = 60  # seconds to wait after a 429, doubled on each repeat (max 15 min)
_MAX_FAILURES = 8  # consecutive throttled/failed requests before giving up for now

_caches: dict[str, dict[str, str]] = {}
_task: asyncio.Task[None] | None = None


# Locales whose region matters to the translator; everything else uses the base code.
_KEEP_REGION = {"zh_cn": "zh-CN", "zh_tw": "zh-TW"}


def target_language(locale: str | None) -> str:
    """UI locale (``es_ES``) -> translator code (``es``); empty means keep the original."""
    value = (locale or "").strip().replace("-", "_").lower()
    if not value or not value[:2].isalpha() or len(value) > 10:
        return ""
    if value in _KEEP_REGION:
        return _KEEP_REGION[value]
    base = value.split("_")[0]
    return "" if base == "en" else base


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


def _retryable(exc: Exception) -> bool:
    """Throttling and server errors are worth waiting for; a rejected text is skipped."""
    if isinstance(exc, httpx2.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return True  # network trouble


async def _fill(texts: list[str], lang: str) -> None:
    cache = _load(lang)
    done = 0
    failures = 0
    wait = _BACKOFF_START
    for text in texts:
        if text in cache:
            continue
        translated: str | None = None
        while True:
            try:
                translated = await _translate(text, lang)
                failures, wait = 0, _BACKOFF_START
                break
            except Exception as exc:
                if not _retryable(exc):
                    break  # skip this text, keep going
                failures += 1
                if failures >= _MAX_FAILURES:
                    log.warning("Achievement translation paused; it will retry later")
                    if done:
                        _save(lang)
                    return
                log.warning(f"Achievement translation throttled; waiting {wait}s")
                await asyncio.sleep(wait)
                wait = min(wait * 2, 900)
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
