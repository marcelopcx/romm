"""Machine translation of achievement texts, cached on disk.

RetroAchievements publishes titles and descriptions in English only. The client
sends its UI language; texts already in the cache are swapped in right away, the
rest are translated in the background (one text at a time, Google Translate's
keyless endpoint) and show up on the next request.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx2

from config import ROMM_BASE_PATH
from logger.logger import log
from utils.context import ctx_httpx_client

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
# DeepL is used when DEEPL_API_KEY is set (free keys end in ":fx"): official, batched,
# and not throttled like the keyless Google endpoint.
DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"
DEEPL_BATCH = 50
_DEEPL_TARGETS = {
    "bg": "BG", "cs": "CS", "de": "DE", "es": "ES", "fr": "FR", "hu": "HU",
    "it": "IT", "ja": "JA", "ko": "KO", "pl": "PL", "pt": "PT-BR", "ro": "RO",
    "ru": "RU", "sv": "SV", "tr": "TR", "zh": "ZH-HANS", "zh-cn": "ZH-HANS",
    "zh-tw": "ZH-HANT",
}  # fmt: skip
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


def _deepl_key() -> str:
    return os.environ.get("DEEPL_API_KEY", "").strip()


def _deepl_target(lang: str) -> str | None:
    return _DEEPL_TARGETS.get(lang.lower())


async def _translate_deepl(texts: list[str], lang: str) -> list[str | None]:
    """A batch through DeepL; results line up with ``texts``."""
    key = _deepl_key()
    response = await ctx_httpx_client.get().post(
        DEEPL_FREE_URL if key.endswith(":fx") else DEEPL_PRO_URL,
        headers={"Authorization": f"DeepL-Auth-Key {key}"},
        json={
            "text": texts,
            "source_lang": "EN",
            "target_lang": _deepl_target(lang),
            "preserve_formatting": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    results = [(t.get("text") or "").strip() or None for t in response.json()["translations"]]
    return results if len(results) == len(texts) else [None] * len(texts)


async def _translate_chunk(chunk: list[str], lang: str) -> list[str | None]:
    if _deepl_key() and _deepl_target(lang):
        return await _translate_deepl(chunk, lang)
    return [await _translate(text, lang) for text in chunk]


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


def _quota_exhausted(exc: Exception) -> bool:
    """DeepL answers 456 once the monthly character quota is used up."""
    return isinstance(exc, httpx2.HTTPStatusError) and exc.response.status_code == 456


async def _fill(texts: list[str], lang: str) -> None:
    cache = _load(lang)
    full_batch = DEEPL_BATCH if _deepl_key() and _deepl_target(lang) else 1
    batch = full_batch
    pending = [t for t in texts if t not in cache]
    done = 0
    failures = 0
    wait = _BACKOFF_START
    index = 0
    while index < len(pending):
        chunk = pending[index : index + batch]
        try:
            results = await _translate_chunk(chunk, lang)
            failures, wait = 0, _BACKOFF_START
            batch = full_batch
        except Exception as exc:
            if _quota_exhausted(exc):
                log.warning("DeepL monthly quota used up; translation paused")
                break
            if not _retryable(exc):
                # A rejected request: retry the texts one by one so a single bad
                # text does not block the rest.
                if len(chunk) > 1:
                    batch = 1
                else:
                    index += 1
                continue
            failures += 1
            if failures >= _MAX_FAILURES:
                log.warning("Achievement translation paused; it will retry later")
                break
            log.warning(f"Achievement translation throttled; waiting {wait}s")
            await asyncio.sleep(wait)
            wait = min(wait * 2, 900)
            continue
        for text, translated in zip(chunk, results):
            if translated:
                cache[text] = translated
                done += 1
        if done and done % _SAVE_EVERY < len(chunk):
            _save(lang)
        index += len(chunk)
        await asyncio.sleep(_PAUSE)
    if done:
        _save(lang)
        log.info(f"Translated {done} achievement texts to '{lang}'")


async def translate_now(texts: list[str], lang: str) -> dict[str, str]:
    """Translate ``texts`` before returning (cache first). Texts that fail stay as they are."""
    cache = _load(lang)
    need = [t for t in dict.fromkeys(texts) if t and t not in cache]
    # Without DeepL the keyless endpoint is throttled, so only do a few per call.
    batch = DEEPL_BATCH if _deepl_key() and _deepl_target(lang) else 1
    limit = len(need) if batch > 1 else 25
    need = need[:limit]
    changed = False
    for start in range(0, len(need), batch):
        chunk = need[start : start + batch]
        try:
            results = await _translate_chunk(chunk, lang)
        except Exception:
            break
        for text, translated in zip(chunk, results):
            if translated:
                cache[text] = translated
                changed = True
    if changed:
        _save(lang)
    return {t: cache.get(t, t) for t in texts}


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
