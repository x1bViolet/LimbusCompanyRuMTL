import msgspec
from pathlib import Path


class FontRule(msgspec.Struct):
    font: str
    path: str


class ReplacementMap(msgspec.Struct):
    repo: str | None = None
    path: str | None = None


class Reference(msgspec.Struct):
    path: str
    repo: str | None = None
    branch: str | None = None


class KeywordShorthands(msgspec.Struct):
    regex: str
    apply_for: list[str]


class Priority(msgspec.Struct):
    order: list[str] = msgspec.field(default_factory=list)


class Config(msgspec.Struct):
    replacement_map: ReplacementMap
    reference: Reference
    font_rules: dict[str, list[FontRule]]
    keyword_shorthands: KeywordShorthands
    priority: Priority
    @staticmethod
    def from_file(path: Path) -> "Config":
        with open(path, "r") as f:
            content = f.read()
        return msgspec.toml.decode(content, type=Config)
