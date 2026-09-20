import re
from pathlib import Path

import pytest

from scripts.json_data import JsonObject
from scripts.models import CloseHighlight, FontRule, XmlEscape
from scripts.text import (
    FontConverter,
    close_highlights,
    convert_font,
    convert_keywords,
    replace_shorthands,
)


def test_font_conversion_preserves_markup_and_placeholders() -> None:
    assert (
        convert_font(
            '<color=red>a</color><sprite name="a"> [a] {0} a',
            {"a": "A", "0": "O"},
            ["sprite"],
        )
        == '<color=red>A</color><sprite name="a"> [a] {0} A'
    )


def test_font_macro_takes_precedence_over_file_rules() -> None:
    data: JsonObject = {
        "dataList": [
            {"name": "[font=title] a"},
            {"name": "a"},
            {"name": "[font=default] a"},
        ]
    }
    converter = FontConverter(
        {"*.json": [FontRule(font="body", path="$.dataList[*].name")]},
        {"title": {"a": "T", "T": "twice"}, "body": {"a": "B", "T": "B"}},
        XmlEscape(),
    )

    converter.process(data, Path("test.json"))

    assert data["dataList"] == [
        {"name": "T"},
        {"name": "B"},
        {"name": "[font=default] a"},
    ]


@pytest.mark.parametrize(
    ("escape_short", "escape_keywords", "expected"),
    [
        (True, True, "[a]<a>A</a>{0}"),
        (False, True, "[A]<a>A</a>{0}"),
        (True, False, "[A]<A>A</A>{O}"),
    ],
)
def test_font_rules_honor_escape_options(
    escape_short: bool, escape_keywords: bool, expected: str
) -> None:
    converter = FontConverter(
        {
            "*.json": [
                FontRule("body", "$.name", escape_short, escape_keywords),
                FontRule("body", "$.name"),
            ]
        },
        {"body": {"a": "A", "0": "O", "A": "twice"}},
        XmlEscape(),
    )
    data: JsonObject = {"name": "[a]<a>a</a>{0}"}

    converter.process(data, Path("first.json"))

    assert data["name"] == expected


def test_font_converter_can_process_new_data_for_the_same_path() -> None:
    converter = FontConverter(
        {"*.json": [FontRule("body", "$.name")]},
        {"body": {"a": "A"}},
        XmlEscape(),
    )
    first: JsonObject = {"name": "a"}
    second: JsonObject = {"name": "a"}

    converter.process(first, Path("same.json"))
    converter.process(second, Path("same.json"))

    assert first == second == {"name": "A"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<unclosed>a", "<unclosed>A"),
        ("<a><a>a</a></a>", "<a><a>A</a></a>"),
        ("<sprite name='a'>a", "<sprite name='a'>A"),
        ("a{}a{0}a", "A{}A{0}A"),
    ],
)
def test_font_conversion_handles_unmatched_nested_and_adjacent_markup(
    text: str, expected: str
) -> None:
    assert convert_font(text, {"a": "A", "0": "O"}, ["sprite"]) == expected


@pytest.mark.parametrize(
    ("text", "color", "sprite"),
    [
        ("[Burn:`Ожог`]", "#123456", "Burn"),
        ("[Burn:`Ожог`](#abcdef;Fire)", "#abcdef", "Fire"),
        ("[Burn:`Ожог`](;Fire)", "#123456", "Fire"),
        ("[Unknown:`Ожог`]", "#f8c200", "Unknown"),
    ],
)
def test_keyword_shorthands_expand_colors_and_sprite_overrides(
    keyword_regex: re.Pattern[str], text: str, color: str, sprite: str
) -> None:
    keyword = "Unknown" if "Unknown" in text else "Burn"
    assert replace_shorthands(text, {"Burn": "#123456"}, keyword_regex) == (
        f'<sprite name="{sprite}"><color={color}>'
        f'<u><link="{keyword}">Ожог</link></u></color>'
    )


def test_keywords_are_converted_in_nested_objects_and_arrays(
    keyword_regex: re.Pattern[str],
) -> None:
    data: JsonObject = {"nested": [["[Burn:`Ожог`]"], {"number": 1, "text": "plain"}]}

    _ = convert_keywords(data, {"Burn": "#123456"}, keyword_regex)

    assert data == {
        "nested": [
            [
                '<sprite name="Burn"><color=#123456><u><link="Burn">Ожог</link></u></color>'
            ],
            {"number": 1, "text": "plain"},
        ]
    }


def test_highlights_only_close_nonempty_unstyled_matches() -> None:
    data: JsonObject = {
        "dataList": [
            {"text": "description"},
            {"text": ""},
            {"text": '<style="highlight">highlighted</style>'},
            {"text": 1},
        ],
        "text": "untouched",
    }

    close_highlights(data, CloseHighlight("$.dataList[*].text", "*.json"))

    assert data == {
        "dataList": [
            {"text": 'description<style="highlight"></style>'},
            {"text": ""},
            {"text": '<style="highlight">highlighted</style>'},
            {"text": 1},
        ],
        "text": "untouched",
    }
