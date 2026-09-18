import json
from pathlib import Path
from typing import cast

type JsonValue = (
    dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
)
type JsonObject = dict[str, JsonValue]


def load_document(path: Path) -> JsonObject:
    value = cast(JsonValue, json.loads(path.read_text(encoding="utf-8-sig")))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def object_list(value: JsonValue) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError("Expected a list of JSON objects")
    result: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Expected a JSON object in list")
        result.append(item)
    return result


def string_field(data: JsonObject, key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(f"Expected a string for {key!r}")
    return value
