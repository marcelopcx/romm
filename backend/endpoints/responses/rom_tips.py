from pydantic import BaseModel


class TipSectionSchema(BaseModel):
    title: str
    text: str


class WikipediaTipsSchema(BaseModel):
    title: str
    language: str
    summary: str
    sections: list[TipSectionSchema]


class CheatEntrySchema(BaseModel):
    description: str
    code: str


class CheatGroupSchema(BaseModel):
    """Cheat codes for one device (GameShark, Game Genie, ...)."""

    device: str
    entries: list[CheatEntrySchema]


class GuideTipsSchema(BaseModel):
    title: str
    pages: list[TipSectionSchema]


class RomTipsSchema(BaseModel):
    """What the open sources say about a game: overview, cheats and guide pages."""

    wikipedia: WikipediaTipsSchema | None
    cheats: list[CheatGroupSchema]
    guide: GuideTipsSchema | None
