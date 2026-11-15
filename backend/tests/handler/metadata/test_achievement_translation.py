import asyncio
import json
from pathlib import Path

import pytest

from handler.metadata import achievement_translation as tr


def _overview():
    def ach(id_, title, description):
        return {"id": id_, "title": title, "description": description}

    return {
        "games": [
            {
                "achievements": [
                    ach("1", "Hello", "Win the game"),
                    ach("vita-NPWR_00-0", "Hola", "Gana"),
                ]
            }
        ]
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tr, "_caches", {})
    monkeypatch.setattr(tr, "_task", None)
    monkeypatch.setattr(tr, "_PAUSE", 0)
    monkeypatch.setattr(tr, "_BACKOFF_START", 0)
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    yield


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("es_ES", "es"),
        ("pt_BR", "pt"),
        ("zh_TW", "zh-TW"),
        ("fr-FR", "fr"),
        ("en_US", ""),
        ("en_GB", ""),
        ("", ""),
        (None, ""),
        ("../../x", ""),
    ],
)
def test_target_language_follows_the_ui_locale(locale: str | None, expected: str):
    assert tr.target_language(locale) == expected


def test_off_when_no_language_is_set():
    overview = _overview()
    assert tr.translate_overview(overview, "") is overview
    assert overview["games"][0]["achievements"][0]["title"] == "Hello"


def test_cached_texts_are_swapped_and_vita_texts_left_alone(tmp_path: Path):
    (tmp_path / "achievement-translations-es.json").write_text(
        json.dumps({"Hello": "Hola", "Win the game": "Gana el juego", "Hola": "X"})
    )
    first, vita = tr.translate_overview(_overview(), "es")["games"][0]["achievements"]
    assert (first["title"], first["description"]) == ("Hola", "Gana el juego")
    assert vita["title"] == "Hola"  # not re-translated through the cache


@pytest.mark.asyncio
async def test_missing_texts_are_translated_in_the_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def fake(text: str, lang: str) -> str | None:
        return f"[{lang}] {text}"

    monkeypatch.setattr(tr, "_translate", fake)
    tr.translate_overview(_overview(), "es")
    assert tr._task is not None
    await tr._task
    saved = json.loads((tmp_path / "achievement-translations-es.json").read_text())
    assert saved == {"Hello": "[es] Hello", "Win the game": "[es] Win the game"}
    first = tr.translate_overview(_overview(), "es")["games"][0]["achievements"][0]
    assert first["title"] == "[es] Hello"


@pytest.mark.asyncio
async def test_throttling_is_waited_out_and_translation_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = {"n": 0}

    async def flaky(text: str, lang: str) -> str | None:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("429")  # network-style error: retryable
        return f"[{lang}] {text}"

    monkeypatch.setattr(tr, "_translate", flaky)
    tr.translate_overview(_overview(), "es")
    assert tr._task is not None
    await tr._task
    saved = json.loads((tmp_path / "achievement-translations-es.json").read_text())
    assert saved == {"Hello": "[es] Hello", "Win the game": "[es] Win the game"}


@pytest.mark.asyncio
async def test_deepl_translates_in_batches_when_a_key_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DEEPL_API_KEY", "abc:fx")
    seen: list[list[str]] = []

    async def fake(texts: list[str], lang: str) -> list[str | None]:
        seen.append(list(texts))
        return [f"[deepl {lang}] {t}" for t in texts]

    monkeypatch.setattr(tr, "_translate_deepl", fake)
    tr.translate_overview(_overview(), "es")
    assert tr._task is not None
    await tr._task
    assert len(seen) == 1 and sorted(seen[0]) == ["Hello", "Win the game"]
    saved = json.loads((tmp_path / "achievement-translations-es.json").read_text())
    assert saved["Hello"] == "[deepl es] Hello"


def test_deepl_target_codes():
    assert tr._deepl_target("es") == "ES"
    assert tr._deepl_target("pt") == "PT-BR"
    assert tr._deepl_target("zh-TW") == "ZH-HANT"
    assert tr._deepl_target("xx") is None


@pytest.mark.asyncio
async def test_a_failing_service_keeps_the_original_text(
    monkeypatch: pytest.MonkeyPatch,
):
    async def boom(text: str, lang: str) -> str | None:
        raise RuntimeError("blocked")

    monkeypatch.setattr(tr, "_translate", boom)
    result = tr.translate_overview(_overview(), "es")
    assert tr._task is not None
    await tr._task
    assert result["games"][0]["achievements"][0]["title"] == "Hello"
    assert not asyncio.iscoroutine(tr._task)
