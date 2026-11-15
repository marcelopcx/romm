import asyncio
from pathlib import Path

import pytest

from handler.metadata import game_tips as gt

CHT = """cheats = 2

cheat0_desc = "Infinite Lives"
cheat0_code = "8001ABCD+0009"
cheat0_enable = false

cheat1_desc = "Max Money"
cheat1_code = "8001FFFF+03E7"
cheat1_enable = false
"""

WIKI = (
    "Crash Team Racing es un videojuego de carreras.\n\n"
    "== Sistema de juego ==\n" + "Se conduce con karts y se usan armas. " * 6 + "\n\n"
    "== Recepción ==\nBien recibido.\n"
)


def test_parse_cht_pairs_descriptions_with_codes():
    assert gt.parse_cht(CHT) == [
        {"description": "Infinite Lives", "code": "8001ABCD+0009"},
        {"description": "Max Money", "code": "8001FFFF+03E7"},
    ]


def test_wikipedia_keeps_gameplay_sections_only():
    summary, sections = gt._wiki_sections(WIKI)
    assert summary.startswith("Crash Team Racing")
    assert [s["title"] for s in sections] == ["Sistema de juego"]


def test_cheat_candidates_follow_no_intro_naming():
    plain = gt._cht_candidates({"fs_name_no_ext": "Advance Wars", "fs_name_no_tags": "Advance Wars"})
    assert ("Code Breaker", "Advance Wars (USA) (Code Breaker).cht") in plain
    tagged = gt._cht_candidates(
        {"fs_name_no_ext": "CTR (USA)", "fs_name_no_tags": "CTR"}
    )
    assert ("GameShark", "CTR (USA) (GameShark).cht") in tagged


def test_names_match_ignoring_case_accents_and_parentheses():
    assert gt._norm(gt._strip_parens("Crash Team Racing (videojuego)")) == gt._norm(
        "crash team racing"
    )
    assert gt._norm("Pokémon") == gt._norm("pokemon")


@pytest.mark.asyncio
async def test_tips_are_gathered_cached_and_translated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    async def wiki(name, language):
        calls["n"] += 1
        return {"title": name, "language": language, "summary": "Resumen", "sections": []}

    async def cheats(rom):
        return [{"device": "GameShark", "entries": [{"description": "Infinite Lives", "code": "1"}]}]

    async def guide(name):
        return {"title": name, "pages": [{"title": "Controls", "text": "Press X."}]}

    async def translate(texts, lang):
        return {t: f"[{lang}] {t}" for t in texts}

    monkeypatch.setattr(gt, "_wikipedia", wiki)
    monkeypatch.setattr(gt, "_cheats", cheats)
    monkeypatch.setattr(gt, "_strategywiki", guide)
    monkeypatch.setattr(gt, "translate_now", translate)

    rom = {"id": 5, "name": "Crash Team Racing", "platform_fs_slug": "psx"}
    tips = await gt.get_tips(rom, "es")
    assert tips["cheats"][0]["entries"][0]["description"] == "[es] Infinite Lives"
    assert tips["guide"]["pages"][0]["text"] == "[es] Press X."
    assert tips["wikipedia"]["language"] == "es"

    again = await gt.get_tips(rom, "es")
    assert again == tips and calls["n"] == 1  # second call came from the cache


@pytest.mark.asyncio
async def test_nothing_found_returns_empty_and_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)

    async def none(*_a):
        return None

    async def empty(_rom):
        return []

    monkeypatch.setattr(gt, "_wikipedia", none)
    monkeypatch.setattr(gt, "_cheats", empty)
    monkeypatch.setattr(gt, "_strategywiki", none)
    tips = await gt.get_tips({"id": 9, "name": "Obscure Game", "platform_fs_slug": "nes"}, "")
    assert tips == {"wikipedia": None, "cheats": [], "guide": None}
    assert not list(tmp_path.iterdir())
    assert asyncio.iscoroutinefunction(gt.get_tips)
