import typing
from pathlib import Path

import msgspec


class FontRule(msgspec.Struct):
    font: str
    path: str
    escape_short_keywords: bool = True
    escape_keywords: bool = True


class IncludedFont(msgspec.Struct):
    path: str
    filename: str


class Font(msgspec.Struct):
    replacement_map_path: str
    repo: str | None = None
    include: list[IncludedFont] = msgspec.field(default_factory=list)


class Reference(msgspec.Struct):
    path: str
    repo: str | None = None
    branch: str | None = None


class KeywordShorthands(msgspec.Struct):
    regex: str
    apply_for: list[str]


class Priority(msgspec.Struct):
    order: list[str] = msgspec.field(default_factory=list)


class XmlEscape(msgspec.Struct):
    singular_keywords: list[str] = msgspec.field(default_factory=list)


class CloseHighlight(msgspec.Struct):
    path: str
    file_pattern: str


class Config(msgspec.Struct):
    font: Font
    reference: Reference
    keyword_shorthands: KeywordShorthands
    priority: Priority
    xml_escape: XmlEscape

    font_rules: dict[str, list[FontRule]] = msgspec.field(default_factory=dict)
    close_highlight: list[CloseHighlight] = msgspec.field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> "Config":
        with open(path, "r") as f:
            content = f.read()
        return msgspec.toml.decode(content, type=Config)


class ReleaseAsset(typing.TypedDict):
    name: str
    browser_download_url: str
