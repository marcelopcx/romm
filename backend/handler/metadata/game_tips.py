"""A game guide built from open wikis, cached on disk and shown inside RomM.

* Wikipedia: summary plus gameplay/story sections, in the UI language.
* StrategyWiki and the game's Fandom wiki: guide pages (walkthrough, items,
  enemies and bosses, data lists such as card passwords, basics).

Pages come through the MediaWiki API as HTML and are reduced to plain blocks
(headings, paragraphs, lists, tables); nothing remote is ever served as HTML.
Text that arrives in English is translated to the UI language and cached,
within a per-game character budget so the DeepL quota lasts.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from config import ROMM_BASE_PATH
from handler.metadata.achievement_translation import translate_now
from logger.logger import log
from utils.context import ctx_httpx_client

CACHE_DIR = Path(ROMM_BASE_PATH) / "config" / "game-tips"
CACHE_TTL = 30 * 86400
_HEADERS = {"User-Agent": "RomM-tips/1.0 (self-hosted game library)"}
_TIMEOUT = 20

_MAX_SUMMARY = 1000
_MAX_WIKI_SECTION = 1800
_MAX_PAGE_CHARS = 6000  # prose per page
_MAX_TABLE_ROWS = 800
_MAX_CELL = 160
_MAX_TRANSLATE_CHARS = 30000  # per game, to protect the translation quota
_CATEGORY_CAPS = {"guide": 14, "items": 8, "enemies": 8, "data": 6, "basics": 6}
CATEGORY_ORDER = ("basics", "guide", "items", "enemies", "data")

# Franchise words in a game name -> Fandom wiki subdomain.
_FANDOM_ALIASES = {
    "yu-gi-oh": "yugioh", "crash": "crashbandicoot", "zelda": "zelda",
    "castlevania": "castlevania", "metroid": "metroid", "sonic": "sonic",
    "kirby": "kirby", "mega man": "megaman", "resident evil": "residentevil",
    "silent hill": "silenthill", "final fantasy": "finalfantasy",
    "dragon quest": "dragonquest", "persona": "megamitensei",
    "digimon": "digimon", "pokemon": "pokemon", "pokémon": "pokemon",
    "star fox": "starfox", "donkey kong": "donkeykong",
    "fire emblem": "fireemblem", "advance wars": "advancewars",
    "street fighter": "streetfighter", "tekken": "tekken", "spyro": "spyro",
    "gran turismo": "granturismo", "bloody roar": "bloodyroar",
    "guitar hero": "guitarhero", "animal crossing": "animalcrossing",
    "pac-man": "pacman", "ms. pac-man": "pacman", "tetris": "tetris",
    "alex kidd": "alexkidd", "mario": "mario", "gravity rush": "gravityrush",
    "rayman": "rayman", "fez": "fez", "grim fandango": "grimfandango",
    "plants vs": "plantsvszombies", "dragon ball": "dragonball",
}  # fmt: skip

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("data", ("card list", "list of", "passwords", "password", "fusion", "recipes",
              "drop list", "drops", "codes")),
    ("enemies", ("enemies", "enemy", "bestiary", "boss", "monster", "opponent", "duelist",
                 "characters", "creatures", "foes")),
    ("items", ("item", "weapon", "equipment", "armor", "armour", "shop", "store",
               "collectible", "treasure", "loot", "rare", "relic", "accessor",
               "inventory", "kinstone", "heart piece", "spell")),
    ("basics", ("controls", "gameplay", "basics", "mechanics", "tips", "tricks",
                "strateg", "secrets", "hidden", "modes", "getting started",
                "difficulty", "unlock", "achievements", "trophies")),
]  # fmt: skip
_SKIP_TITLES = re.compile(
    r"gallery|trailer|promotional|soundtrack|music|staff|credits|references|"
    r"table of contents|template|category|talk:|user:|file:",
    re.IGNORECASE,
)

_WIKI_SECTIONS = re.compile(
    r"gameplay|jugabilidad|sistema de juego|modo de juego|mec[aá]nica|"
    r"historia|argumento|trama|premisa|story|plot|sinopsis|synopsis",
    re.IGNORECASE,
)


# --- text helpers --------------------------------------------------------------


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)))


def _strip_parens(title: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", title).strip()


def _name_variants(name: str) -> list[str]:
    """The name, then its parts around ":" or " - " ("CTR: Crash Team Racing" -> "Crash Team Racing")."""
    variants = [name]
    for part in re.split(r"\s*(?::|\s-\s)\s*", name):
        part = part.strip()
        if len(part) >= 4 and part not in variants:
            variants.append(part)
    return variants


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _clean(text: str) -> str:
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"\[(?:edit|\d+|citation needed)\]", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def category_of(title: str) -> str:
    lowered = title.lower()
    for category, words in _CATEGORY_KEYWORDS:
        if any(word in lowered for word in words):
            return category
    return "guide"


# --- HTML -> blocks ------------------------------------------------------------

_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "wbr"}
_SKIP_TAGS = {"script", "style", "sup", "figure", "nav", "noscript", "button", "form", "svg", "aside"}
_SKIP_CLASSES = {
    "toc", "navbox", "infobox", "portable-infobox", "mw-editsection", "reference",
    "references", "reflist", "thumb", "gallery", "noprint", "hatnote", "mbox",
    "ambox", "metadata", "navigation-not-searchable", "mw-empty-elt", "printfooter",
    "catlinks", "wikia-gallery", "navbar", "toccolours", "sidebar",
}  # fmt: skip
_BLOCK_TEXT = {"p", "dd", "dt", "blockquote"}


class _BlockParser(HTMLParser):
    def __init__(self, max_chars: int, max_rows: int) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.max_chars = max_chars
        self.max_rows = max_rows
        self.chars = 0
        self.stack: list[tuple[str, bool]] = []
        self.skip = 0
        self.buf: list[str] = []
        self.kind = "paragraph"
        self.list_items: list[str] | None = None
        self.in_li = False
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table_depth = 0

    # -- helpers
    def _flush_text(self) -> None:
        text = _clean("".join(self.buf))
        self.buf = []
        if not text:
            return
        if self.kind == "heading":
            self.blocks.append({"type": "heading", "text": text})
        elif self.in_li and self.list_items is not None:
            self.list_items.append(text)
        elif self.chars < self.max_chars and len(text) > 1:
            self.blocks.append({"type": "paragraph", "text": text})
            self.chars += len(text)
        self.kind = "paragraph"

    def _flush_list(self) -> None:
        if self.list_items:
            items = [i for i in self.list_items if i][:60]
            if items and self.chars < self.max_chars:
                self.blocks.append({"type": "list", "items": items})
                self.chars += sum(len(i) for i in items)
        self.list_items = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    # -- parser hooks
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag == "br" and not self.skip:
                self.buf.append(" ")
            return
        classes = self._classes(attrs)
        style = next((v or "" for k, v in attrs if k == "style"), "")
        element_id = next((v or "" for k, v in attrs if k == "id"), "")
        skip_here = (
            tag in _SKIP_TAGS
            or bool(classes & _SKIP_CLASSES)
            or element_id == "toc"
            or "display:none" in style.replace(" ", "")
        )
        if tag == "table" and self.table is not None:
            skip_here = True  # nested table
        self.stack.append((tag, skip_here))
        if skip_here:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self._flush_text()
            self._flush_list()
            self.table, self.table_depth = [], len(self.stack)
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif self.table is not None:
            return
        elif re.fullmatch(r"h[2-6]", tag):
            self._flush_text()
            self._flush_list()
            self.kind = "heading"
        elif tag in ("ul", "ol"):
            self._flush_text()
            if self.list_items is None:
                self.list_items = []
        elif tag == "li":
            self._flush_text()
            self.in_li = True
        elif tag in _BLOCK_TEXT or tag == "div":
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            top, skipped = self.stack.pop()
            if skipped:
                self.skip -= 1
            if top == tag:
                break
            # an unclosed child: treat it as closed
        if self.skip:
            return
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_clip(_clean("".join(self.cell)), _MAX_CELL))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if any(self.row) and len(self.table) <= self.max_rows:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None and len(self.stack) < self.table_depth:
            self._emit_table()
        elif self.table is not None:
            return
        elif re.fullmatch(r"h[2-6]", tag):
            self._flush_text()
        elif tag == "li":
            self._flush_text()
            self.in_li = False
        elif tag in ("ul", "ol"):
            self._flush_list()
        elif tag in _BLOCK_TEXT or tag == "div":
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.buf.append(data)

    def _emit_table(self) -> None:
        rows = self.table or []
        self.table = None
        if len(rows) < 2:
            return
        width = max(len(r) for r in rows)
        if width < 2 or width > 12:
            return
        rows = [r + [""] * (width - len(r)) for r in rows]
        self.blocks.append({"type": "table", "headers": rows[0], "rows": rows[1:]})

    def close(self) -> None:
        super().close()
        self._flush_text()
        self._flush_list()


def html_to_blocks(html: str, max_chars: int = _MAX_PAGE_CHARS, max_rows: int = _MAX_TABLE_ROWS) -> list[dict[str, Any]]:
    parser = _BlockParser(max_chars, max_rows)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        log.warning("Could not parse a wiki page")
    blocks = parser.blocks
    # a heading with nothing under it adds noise
    cleaned: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if block["type"] == "heading":
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            if following is None or following["type"] == "heading":
                continue
        cleaned.append(block)
    return cleaned


# --- HTTP ----------------------------------------------------------------------


def _api(host: str) -> str:
    """Fandom serves the API at the root; the other MediaWiki sites under /w/."""
    return f"https://{host}/api.php" if host.endswith(".fandom.com") else f"https://{host}/w/api.php"



async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        response = await ctx_httpx_client.get().get(
            url, params=params, headers=_HEADERS, timeout=_TIMEOUT
        )
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def _parse_page(host: str, title: str) -> str | None:
    data = await _get_json(
        _api(host),
        {"action": "parse", "page": title, "prop": "text", "redirects": 1,
         "disableeditsection": 1, "format": "json"},
    )  # fmt: skip
    text = ((data or {}).get("parse") or {}).get("text")
    if isinstance(text, dict):
        text = text.get("*")
    return text if isinstance(text, str) else None


async def _titles_with_prefix(host: str, prefix: str, limit: int = 100) -> list[str]:
    data = await _get_json(
        _api(host),
        {"action": "query", "list": "allpages", "apprefix": prefix, "aplimit": limit,
         "apnamespace": 0, "format": "json"},
    )  # fmt: skip
    return [p["title"] for p in ((data or {}).get("query") or {}).get("allpages", [])]


async def _search_titles(host: str, query: str, limit: int = 8) -> list[str]:
    data = await _get_json(
        _api(host),
        {"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
         "srnamespace": 0, "format": "json"},
    )  # fmt: skip
    return [r["title"] for r in ((data or {}).get("query") or {}).get("search", [])]


# --- Wikipedia -----------------------------------------------------------------


def _wiki_sections(extract: str) -> tuple[str, list[dict[str, str]]]:
    parts = re.split(r"\n==+ *(.+?) *==+\n", "\n" + extract)
    summary = parts[0].strip()
    sections = []
    for title, body in zip(parts[1::2], parts[2::2]):
        body = re.sub(r"\n==+ .+? ==+\n", "\n", body).strip()
        if _WIKI_SECTIONS.search(title) and len(body) > 80:
            sections.append({"title": title.strip(), "text": _clip(body, _MAX_WIKI_SECTION)})
    return summary, sections


async def _wikipedia(name: str, language: str) -> dict[str, Any] | None:
    host = f"{language}.wikipedia.org"
    titles = await _search_titles(host, name, 6)
    wanted = _norm(name)
    title = next((t for t in titles if _norm(_strip_parens(t)) == wanted), None)
    if title is None:
        return None
    data = await _get_json(
        _api(host),
        {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
         "titles": title, "format": "json"},
    )  # fmt: skip
    pages = list(((data or {}).get("query") or {}).get("pages", {}).values())
    extract = pages[0].get("extract", "") if pages else ""
    if len(extract) < 120:
        return None
    summary, sections = _wiki_sections(extract)
    return {"title": title, "language": language, "summary": _clip(summary, _MAX_SUMMARY), "sections": sections}


# --- wiki guides ----------------------------------------------------------------


def _wiki_candidates(name: str) -> list[str]:
    """Fandom subdomains worth trying for this game."""
    lowered = name.lower()
    hosts: list[str] = []
    for key, slug in _FANDOM_ALIASES.items():
        if key in lowered and slug not in hosts:
            hosts.append(slug)
    return hosts[:2]


async def _is_wiki(host: str) -> bool:
    data = await _get_json(
        f"https://{host}/api.php", {"action": "query", "meta": "siteinfo", "format": "json"}
    )
    return bool(data and data.get("query"))


async def _candidate_pages(host: str, label: str, name: str) -> list[tuple[str, str, str]]:
    """(host, title, source label) of pages about ``name`` on one wiki."""
    wanted = _norm(name)
    titles: list[str] = []
    fandom = host.endswith(".fandom.com")
    multiword = len(name.split()) >= 2
    # "Game/Subpage" is always the game's own. ": " and " " prefixes and free
    # text search also catch sibling games, so only a multi-word name is safe.
    titles.extend(await _titles_with_prefix(host, name + "/"))
    if fandom and multiword:
        titles.extend(await _titles_with_prefix(host, name + ":"))
        titles.extend(await _titles_with_prefix(host, name + " "))
        for query in (name, f"{name} items", f"{name} enemies bosses", f"{name} guide walkthrough"):
            titles.extend(await _search_titles(host, query))
    chosen: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for title in titles:
        key = _norm(title)
        if key in seen or _SKIP_TITLES.search(title):
            continue
        # Subpages of the game, or pages whose title carries the game's name.
        if wanted not in key and wanted not in _norm(title.split("/")[0]):
            continue
        if key == wanted:
            continue  # the game's own page is the overview, not a guide page
        seen.add(key)
        chosen.append((host, title, label))
    return chosen


def _display_title(title: str, name: str) -> str:
    """Drop the game's name prefix so tabs read "Controls", not "Game/Controls"."""
    for variant in _name_variants(name):
        for sep in ("/", ": ", " - "):
            if title.lower().startswith((variant + sep).lower()):
                return title[len(variant) + len(sep):].strip() or title
    return title


async def _collect_pages(name: str) -> dict[str, list[dict[str, Any]]]:
    sources: list[tuple[str, str]] = [("strategywiki.org", "StrategyWiki")]
    for slug in _wiki_candidates(name):
        host = f"{slug}.fandom.com"
        if await _is_wiki(host):
            sources.append((host, "Fandom"))

    candidates: list[tuple[str, str, str]] = []
    for host, label in sources:
        for variant in _name_variants(name):
            found = await _candidate_pages(host, label, variant)
            if found:
                candidates.extend(found)
                break

    by_category: dict[str, list[tuple[str, str, str]]] = {c: [] for c in _CATEGORY_CAPS}
    for host, title, label in candidates:
        category = category_of(_display_title(title, name))
        bucket = by_category[category]
        if len(bucket) < _CATEGORY_CAPS[category]:
            bucket.append((host, title, label))

    semaphore = asyncio.Semaphore(6)

    async def fetch(host: str, title: str, label: str) -> tuple[str, dict[str, Any] | None]:
        async with semaphore:
            html = await _parse_page(host, title)
        if not html:
            return title, None
        blocks = html_to_blocks(html)
        text_size = sum(len(b.get("text") or "") + sum(len(i) for i in b.get("items") or []) for b in blocks)
        has_table = any(b["type"] == "table" for b in blocks)
        if text_size < 200 and not has_table:
            return title, None
        return title, {"title": _display_title(title, name), "source": label, "blocks": blocks}

    jobs: list[tuple[str, Any]] = []
    for category, items in by_category.items():
        for host, title, label in items:
            jobs.append((category, fetch(host, title, label)))
    results = await asyncio.gather(*(job for _, job in jobs))
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in _CATEGORY_CAPS}
    seen: set[Any] = set()
    for (category, _), (_, page) in zip(jobs, results):
        if not page:
            continue
        signature = _signature(page)
        if signature in seen:  # the same list reached through several pages
            continue
        seen.add(signature)
        out[category].append(page)
    return out


def _signature(page: dict[str, Any]) -> Any:
    """Identifies a page by its biggest table, or by its opening text."""
    tables = [b for b in page["blocks"] if b["type"] == "table"]
    if tables:
        biggest = max(tables, key=lambda b: len(b["rows"]))
        return ("table", len(biggest["rows"]), tuple(map(tuple, biggest["rows"][:3])))
    return ("text", page["title"], str(page["blocks"][:2]))


# --- translation ----------------------------------------------------------------


def _translatable(page: dict[str, Any]) -> list[str]:
    texts = [page["title"]]
    for block in page["blocks"]:
        if block["type"] in ("heading", "paragraph"):
            texts.append(block["text"])
        elif block["type"] == "list":
            texts.extend(block["items"])
        elif block["type"] == "table":
            texts.extend(h for h in block["headers"] if h)
            texts.extend(
                cell for row in block["rows"][:30] for cell in row if len(cell) > 40
            )
    return texts


def _apply(page: dict[str, Any], done: dict[str, str]) -> None:
    get = lambda s: done.get(s, s)  # noqa: E731
    page["title"] = get(page["title"])
    for block in page["blocks"]:
        if block["type"] in ("heading", "paragraph"):
            block["text"] = get(block["text"])
        elif block["type"] == "list":
            block["items"] = [get(i) for i in block["items"]]
        elif block["type"] == "table":
            block["headers"] = [get(h) for h in block["headers"]]
            block["rows"] = [[get(c) if len(c) > 40 else c for c in row] for row in block["rows"]]


async def _translate_tips(tips: dict[str, Any], lang: str) -> None:
    if not lang:
        return
    pages = [p for cat in tips["categories"] for p in cat["pages"]]
    texts: list[str] = []
    budget = _MAX_TRANSLATE_CHARS
    for page in pages:
        for text in _translatable(page):
            if budget <= 0:
                break
            texts.append(text)
            budget -= len(text)
    wiki = tips.get("wikipedia")
    if wiki and wiki["language"] != lang:  # fell back to English
        texts.extend((wiki["summary"], *(s["title"] for s in wiki["sections"]), *(s["text"] for s in wiki["sections"])))
    if not texts:
        return
    done = await translate_now(texts, lang)
    for page in pages:
        _apply(page, done)
    if wiki and wiki["language"] != lang:
        wiki["summary"] = done.get(wiki["summary"], wiki["summary"])
        for s in wiki["sections"]:
            s["title"] = done.get(s["title"], s["title"])
            s["text"] = done.get(s["text"], s["text"])


# --- orchestration ---------------------------------------------------------------


def _cache_file(rom_id: int, lang: str) -> Path:
    return CACHE_DIR / f"{rom_id}-{lang or 'en'}-v2.json"


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


async def get_tips(rom: dict[str, Any], lang: str) -> dict[str, Any]:
    """Guide for one ROM. ``lang`` is a translator code ("es"), or "" to keep English."""
    cached = _read_cache(rom["id"], lang)
    if cached is not None:
        return cached
    name = rom.get("name") or rom.get("fs_name_no_tags") or rom.get("fs_name_no_ext") or ""
    name = _strip_parens(name).strip()
    wiki_langs = [lang, "en"] if lang and lang != "en" else ["en"]

    async def wiki() -> dict[str, Any] | None:
        for variant in _name_variants(name):
            for language in wiki_langs:
                result = await _wikipedia(variant, language)
                if result:
                    return result
        return None

    wikipedia, pages = await asyncio.gather(wiki(), _collect_pages(name))
    categories = [
        {"id": category, "pages": pages[category]}
        for category in CATEGORY_ORDER
        if pages.get(category)
    ]
    tips: dict[str, Any] = {"wikipedia": wikipedia, "categories": categories}
    await _translate_tips(tips, lang)
    if wikipedia or categories:
        _write_cache(rom["id"], lang, tips)
    return tips
