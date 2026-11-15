"""PS Vita trophies read from the console's own database, with no PSN session.

``vita-sync`` copies the unlocked state out of ``trophy_local.db`` into
``<ROMM_BASE_PATH>/config/vita-trophies.json``; this module joins it with the
library's PS Vita ROMs and renders it in the same shape as RetroAchievements
games, so the achievements views show both without changes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ROMM_BASE_PATH
from handler.metadata.earned_achievements import (
    AchievementGame,
    AchievementOverview,
    CatalogAchievement,
    _completion_rank,
    _empty_counts,
    _group_covers,
    _public_badge_path,
    _text,
)
from logger.logger import log

TROPHIES_FILE = Path(ROMM_BASE_PATH) / "config" / "vita-trophies.json"

_TITLE_ID = re.compile(r"\[(PCS[A-Z]\d{5})\]")
# PSN grade -> (label, points). The points mirror the PSN trophy values.
_GRADES: dict[int, tuple[str, int]] = {
    1: ("platinum", 180),
    2: ("gold", 90),
    3: ("silver", 30),
    4: ("bronze", 15),
}
_HIDDEN_TITLE = "Trofeo oculto"


def load_trophies(path: Path = TROPHIES_FILE) -> list[dict[str, Any]]:
    """Titles from the sync file; empty when it is missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.exception("Could not read PS Vita trophies")
        return []
    titles = data.get("titles") if isinstance(data, dict) else None
    return [t for t in titles if isinstance(t, dict)] if isinstance(titles, list) else []


def _earned_at(value: object) -> str | None:
    """Vita ISO timestamp -> the ``YYYY-MM-DD HH:MM:SS`` shape RetroAchievements uses."""
    text = _text(value)
    if text is None or text.startswith("0001-"):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def build_vita_games(
    roms: Sequence[Mapping[str, Any]], titles: Sequence[Mapping[str, Any]]
) -> list[AchievementGame]:
    """One game per trophy title whose ``PCS`` id matches a library ROM."""
    by_title_id: dict[str, Mapping[str, Any]] = {}
    for rom in sorted(roms, key=lambda r: r["id"]):
        match = _TITLE_ID.search(rom.get("fs_name") or "")
        if match:
            by_title_id.setdefault(match.group(1), rom)

    games: list[AchievementGame] = []
    for title in titles:
        rom = by_title_id.get(_text(title.get("title_id")) or "")
        trophies = title.get("trophies")
        if rom is None or not isinstance(trophies, list) or not trophies:
            continue

        items: list[CatalogAchievement] = []
        counts = _empty_counts()
        earned_n = points_earned = points_total = 0
        for order, trophy in enumerate(trophies):
            if not isinstance(trophy, dict):
                continue
            kind, points = _GRADES.get(trophy.get("grade"), ("bronze", 15))
            earned = bool(trophy.get("unlocked"))
            masked = bool(trophy.get("hidden")) and not earned
            points_total += points
            if earned:
                earned_n += 1
                points_earned += points
                counts["win_condition" if kind == "platinum" else "other"] += 1
            items.append(
                {
                    "id": f"vita-{title.get('npcommid')}-{trophy.get('id')}",
                    "title": _HIDDEN_TITLE if masked else _text(trophy.get("title")),
                    "description": None if masked else _text(trophy.get("description")),
                    "points": points,
                    "badge_url": None,
                    "badge_path": _public_badge_path(trophy.get("icon")),
                    "badge_url_lock": None,
                    "badge_path_lock": None,
                    "type": "win_condition" if kind == "platinum" else None,
                    "display_order": order,
                    "earned": earned,
                    "earned_at": _earned_at(trophy.get("time_unlocked"))
                    if earned
                    else None,
                }
            )
        if not items:
            continue

        large, small, remote = _group_covers((rom,))
        games.append(
            {
                "rom_id": rom["id"],
                "name": rom["name"],
                "platform_name": rom.get("platform_name"),
                "platform_slug": _text(rom.get("platform_slug")),
                "platform_fs_slug": _text(rom.get("platform_fs_slug")),
                "cover_url": None,
                "path_cover_large": large,
                "path_cover_small": small,
                "url_cover": remote,
                "title_url": None,
                "ingame_url": None,
                "box_art_url": None,
                "earned": earned_n,
                "total": len(items),
                "points_earned": points_earned,
                "points_total": points_total,
                "earned_by_type": counts,
                "achievements": items,
            }
        )
    return games


def merge_vita_games(
    overview: AchievementOverview, games: Sequence[AchievementGame]
) -> AchievementOverview:
    """Add Vita games to a RetroAchievements overview, keeping its sort order."""
    if not games:
        return overview
    present = {game["rom_id"] for game in overview["games"]}
    extra = [game for game in games if game["rom_id"] not in present]
    if not extra:
        return overview

    merged = list(overview["games"]) + extra
    merged.sort(
        key=lambda g: (
            -_completion_rank(g["earned"], g["total"]),
            -g["points_earned"],
            g["name"].casefold(),
        )
    )
    counts = dict(overview["earned_by_type"])
    for game in extra:
        for key, value in game["earned_by_type"].items():
            counts[key] += value
    return {
        "linked": True,
        "synced": True,
        "earned": overview["earned"] + sum(g["earned"] for g in extra),
        "total": overview["total"] + sum(g["total"] for g in extra),
        "points_earned": overview["points_earned"]
        + sum(g["points_earned"] for g in extra),
        "points_total": overview["points_total"] + sum(g["points_total"] for g in extra),
        "earned_by_type": counts,  # type: ignore[typeddict-item]
        "games": merged,
    }
