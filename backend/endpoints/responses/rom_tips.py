from typing import Literal

from pydantic import BaseModel


class TipSectionSchema(BaseModel):
    title: str
    text: str


class WikipediaTipsSchema(BaseModel):
    title: str
    language: str
    summary: str
    sections: list[TipSectionSchema]


class TipBlockSchema(BaseModel):
    """One piece of a guide page: a heading, a paragraph, a list or a table."""

    type: Literal["heading", "paragraph", "list", "table"]
    text: str | None = None
    items: list[str] | None = None
    headers: list[str] | None = None
    rows: list[list[str]] | None = None


class TipPageSchema(BaseModel):
    title: str
    source: str
    blocks: list[TipBlockSchema]


class TipCategorySchema(BaseModel):
    """Guide pages of one kind: basics, guide, items, enemies or data."""

    id: Literal["basics", "guide", "items", "enemies", "data"]
    pages: list[TipPageSchema]


class RomTipsSchema(BaseModel):
    """What the open sources say about a game: an overview plus guide pages."""

    wikipedia: WikipediaTipsSchema | None
    categories: list[TipCategorySchema]
