from pathlib import Path

import pytest

from handler.metadata import game_tips as gt

PAGE = """
<div class="toc"><ul><li>Contents</li></ul></div>
<table class="infobox"><tr><td>Infobox</td><td>skip me</td></tr></table>
<h2>Shop<span class="mw-editsection">[edit]</span></h2>
<p>Buy cards with Star Chips.<sup>[1]</sup> Passwords are eight digits.</p>
<ul><li>Blue-Eyes White Dragon</li><li>Dark Magician</li></ul>
<table>
  <tr><th>Card</th><th>Password</th><th>Cost</th></tr>
  <tr><td>Blue-Eyes White Dragon</td><td>89631139</td><td>999,999</td></tr>
  <tr><td>Mystical Elf</td><td>15025844</td><td>160</td></tr>
</table>
<h2>Empty heading</h2>
<div class="navbox">Nav</div>
"""


def test_html_becomes_plain_blocks_without_the_noise():
    blocks = gt.html_to_blocks(PAGE)
    assert blocks[0] == {"type": "heading", "text": "Shop"}
    assert blocks[1] == {
        "type": "paragraph",
        "text": "Buy cards with Star Chips. Passwords are eight digits.",
    }
    assert blocks[2] == {
        "type": "list",
        "items": ["Blue-Eyes White Dragon", "Dark Magician"],
    }
    table = blocks[3]
    assert table["type"] == "table"
    assert table["headers"] == ["Card", "Password", "Cost"]
    assert table["rows"][1] == ["Mystical Elf", "15025844", "160"]
    # Infobox, contents list, nav box and the heading with nothing under it are gone.
    assert len(blocks) == 4
    assert "Infobox" not in str(blocks)


def test_wide_data_tables_are_kept():
    cols = 9  # a card list: number, name, type, ..., password, cost
    head = "".join(f"<th>c{i}</th>" for i in range(cols))
    row = "".join(f"<td>v{i}</td>" for i in range(cols))
    blocks = gt.html_to_blocks(f"<table><tr>{head}</tr><tr>{row}</tr></table>")
    assert blocks and blocks[0]["type"] == "table" and len(blocks[0]["headers"]) == 9


def test_api_path_depends_on_the_wiki():
    assert gt._api("yugioh.fandom.com") == "https://yugioh.fandom.com/api.php"
    assert gt._api("strategywiki.org") == "https://strategywiki.org/w/api.php"
    assert gt._api("es.wikipedia.org") == "https://es.wikipedia.org/w/api.php"


def test_tables_are_capped_and_never_carry_markup():
    rows = "".join(f"<tr><td>{i}</td><td><b>x</b>{i}</td></tr>" for i in range(50))
    blocks = gt.html_to_blocks(f"<table><tr><th>#</th><th>v</th></tr>{rows}</table>", max_rows=10)
    assert len(blocks[0]["rows"]) == 10
    assert "<" not in str(blocks)


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("Controls", "basics"),
        ("Items", "items"),
        ("Shop", "items"),
        ("Bosses", "enemies"),
        ("Duelists", "enemies"),
        ("Card List 001 - 200", "data"),
        ("Bestiary", "enemies"),
        ("Deepwood Shrine", "guide"),
    ],
)
def test_pages_are_sorted_into_categories(title: str, category: str):
    assert gt.category_of(title) == category


def test_name_variants_and_display_titles():
    assert gt._name_variants("CTR: Crash Team Racing") == ["CTR: Crash Team Racing", "Crash Team Racing"]
    assert gt._display_title("Crash Team Racing/Controls", "Crash Team Racing") == "Controls"
    assert gt._display_title("Yu-Gi-Oh! Forbidden Memories: Card List 001 - 200", "Yu-Gi-Oh! Forbidden Memories") == "Card List 001 - 200"


def test_the_same_list_reached_twice_is_kept_once():
    table = {"type": "table", "headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]}
    one = {"title": "Card List", "source": "Fandom", "blocks": [table]}
    two = {"title": "Card List 001 - 200", "source": "Fandom", "blocks": [dict(table)]}
    assert gt._signature(one) == gt._signature(two)
    assert gt._signature(one) != gt._signature({"title": "x", "source": "s", "blocks": [{"type": "paragraph", "text": "t"}]})


def test_wikipedia_keeps_gameplay_sections_only():
    extract = "Intro text.\n\n== Sistema de juego ==\n" + "Se conduce con karts. " * 8 + "\n\n== Recepción ==\nBien.\n"
    summary, sections = gt._wiki_sections(extract)
    assert summary == "Intro text."
    assert [s["title"] for s in sections] == ["Sistema de juego"]


@pytest.mark.asyncio
async def test_guide_is_gathered_translated_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    async def wiki(name, language):
        calls["n"] += 1
        return {"title": name, "language": language, "summary": "Resumen", "sections": []}

    async def pages(name):
        return {
            "items": [
                {
                    "title": "Items",
                    "source": "StrategyWiki",
                    "blocks": [
                        {"type": "paragraph", "text": "Find the rare sword."},
                        {"type": "table", "headers": ["Item", "Where"], "rows": [["Sword", "Cave"]]},
                    ],
                }
            ],
            "guide": [],
        }

    async def translate(texts, lang):
        return {t: f"[{lang}] {t}" for t in texts}

    monkeypatch.setattr(gt, "_wikipedia", wiki)
    monkeypatch.setattr(gt, "_collect_pages", pages)
    monkeypatch.setattr(gt, "translate_now", translate)

    rom = {"id": 5, "name": "Some Game (USA)"}
    tips = await gt.get_tips(rom, "es")
    (category,) = tips["categories"]
    assert category["id"] == "items"
    page = category["pages"][0]
    assert page["title"] == "[es] Items"
    assert page["blocks"][0]["text"] == "[es] Find the rare sword."
    assert page["blocks"][1]["headers"] == ["[es] Item", "[es] Where"]
    assert page["blocks"][1]["rows"] == [["Sword", "Cave"]]  # short cells are names: untouched
    assert tips["wikipedia"]["language"] == "es"

    again = await gt.get_tips(rom, "es")
    assert again == tips and calls["n"] == 1


@pytest.mark.asyncio
async def test_nothing_found_returns_empty_and_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)

    async def none(*_a):
        return None

    async def nothing(_name):
        return {}

    monkeypatch.setattr(gt, "_wikipedia", none)
    monkeypatch.setattr(gt, "_collect_pages", nothing)
    tips = await gt.get_tips({"id": 9, "name": "Obscure Game"}, "")
    assert tips == {"wikipedia": None, "categories": []}
    assert not list(tmp_path.iterdir())
