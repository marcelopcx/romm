import json
from pathlib import Path

from handler.metadata.earned_achievements import _empty_overview
from handler.metadata.vita_trophies import (
    build_vita_games,
    load_trophies,
    merge_vita_games,
)

ROM = {
    "id": 7,
    "name": "Plants vs Zombies",
    "fs_name": "Plants vs Zombies [PCSE00064].zip",
    "platform_name": "PS Vita",
    "platform_slug": "psvita",
    "platform_fs_slug": "psvita",
    "path_cover_l": None,
    "path_cover_s": None,
    "url_cover": "https://example.test/cover.png",
    "updated_at": None,
}


def _title(**over):
    base = {
        "npcommid": "NPWR02124_00",
        "title_id": "PCSE00064",
        "title": "Plantas Contra Zombis",
        "trophies": [
            {
                "id": 0,
                "title": "Primero",
                "description": "d",
                "grade": 4,
                "hidden": 0,
                "unlocked": 1,
                "icon": "vita-trophies/NPWR02124_00/TROP000.PNG",
                "time_unlocked": "2026-01-15T20:31:17.13Z",
            },
            {
                "id": 1,
                "title": "Secreto",
                "description": "no se ve",
                "grade": 1,
                "hidden": 1,
                "unlocked": 0,
                "time_unlocked": "0001-01-01T00:00:00.00Z",
            },
        ],
    }
    base.update(over)
    return base


def test_matches_rom_by_title_id_and_counts_points():
    (game,) = build_vita_games([ROM], [_title()])
    assert game["rom_id"] == 7
    assert game["cover_url"] == "https://example.test/cover.png"
    assert (game["earned"], game["total"]) == (1, 2)
    assert (game["points_earned"], game["points_total"]) == (15, 195)
    first, second = game["achievements"]
    assert first["earned_at"] == "2026-01-15 20:31:17"
    assert first["badge_path"] == (
        "/assets/romm/resources/vita-trophies/NPWR02124_00/TROP000.PNG"
    )
    assert game["achievements"][1]["badge_path"] is None
    assert second["earned_at"] is None
    assert second["title"] == "Trofeo oculto" and second["description"] is None
    assert game["earned_by_type"]["other"] == 1


def test_falls_back_to_title_text_when_the_id_is_unknown():
    rom = {**ROM, "name": "FROBISHER SAYS!", "fs_name": "FROBISHER SAYS! [PCSA00050].zip"}
    (game,) = build_vita_games([rom], [_title(title_id=None, title="Frobisher Says!™")])
    assert game["rom_id"] == 7


def test_title_without_matching_rom_is_skipped():
    assert build_vita_games([ROM], [_title(title_id="PCSE99999", title="Otro")]) == []


def test_merge_adds_to_totals_and_marks_synced():
    games = build_vita_games([ROM], [_title()])
    merged = merge_vita_games(_empty_overview(linked=False, synced=False), games)
    assert merged["linked"] and merged["synced"]
    assert (merged["earned"], merged["total"]) == (1, 2)
    assert len(merged["games"]) == 1


def test_load_trophies_tolerates_missing_and_broken_files(tmp_path: Path):
    assert load_trophies(tmp_path / "nope.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    assert load_trophies(broken) == []
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"titles": [_title()]}))
    assert len(load_trophies(ok)) == 1


def test_extra_catalog_fills_titles_the_console_lacks(tmp_path: Path):
    main = tmp_path / "main.json"
    extra = tmp_path / "extra.json"
    main.write_text(json.dumps({"titles": [_title()]}))
    extra.write_text(
        json.dumps(
            {
                "titles": [
                    _title(npcommid="NPWR02457_00", title_id="PCSA00011"),
                    _title(npcommid="DUP", title_id="PCSE00064"),
                ]
            }
        )
    )
    ids = [t["title_id"] for t in load_trophies(main, extra)]
    assert ids == ["PCSE00064", "PCSA00011"]
