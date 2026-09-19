import json
from pathlib import Path

import msgspec
import pytest

from scripts.build import main, merge_by_id, merge_by_order
from scripts.json_data import JsonObject, JsonValue, load_document
from scripts.models import Config


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8-sig")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text(
        r"""
[font]
replacement_map_path = "replacement_map.json"
[[font.include]]
path = "Context/font.ttf"
filename = "font.ttf"
[reference]
path = "reference"
[keyword_shorthands]
regex = '\[(?P<keyword_id>\w+):`(?P<text>.*?)`\](\((?P<color>#[a-fA-F0-9]{6})?(;(?P<sprite_id>\w+))?\))?'
apply_for = ["UI.json"]
[priority]
order = ["StoryData/*.json", "Order.json"]
[xml_escape]
singular_keywords = ["sprite", "style"]
[rpg]
dialogue_files = ["RPGSystem/*.json"]
[[font_rules."UI.json"]]
font = "body"
path = "$.dataList[*].text"
[[close_highlight]]
file_pattern = "UI.json"
path = "$.dataList[*].text"
""",
        encoding="utf-8",
    )
    _ = (tmp_path / "replacement_map.json").write_text('{"body": {"a": "A"}}')
    _ = (tmp_path / "font.ttf").write_bytes(b"font content")
    colors = tmp_path / "data/build/keyword_colors.txt"
    colors.parent.mkdir(parents=True)
    _ = colors.write_text("\nBurn ¤ #123456\n", encoding="utf-8")
    write_json(
        tmp_path / "story/entities/tellers.json",
        [{"original": "Dante", "translation": "Данте"}],
    )
    write_json(tmp_path / "story/entities/titles.json", [])
    write_json(tmp_path / "story/entities/places.json", {})
    (tmp_path / "reference").mkdir()
    return config_path


def test_merge_preserves_reference_order_and_fallbacks() -> None:
    reference: list[JsonObject] = [{"id": 2, "text": "two"}, {"id": 1, "text": "one"}]
    localized: list[JsonObject] = [{"id": 1, "text": "один"}, {"id": 3, "text": "три"}]

    assert merge_by_id(reference, localized, Path("test.json")) == [
        {"id": 2, "text": "two"},
        {"id": 1, "text": "один"},
    ]
    assert merge_by_order(reference, localized[:1]) == [
        {"id": 1, "text": "один"},
        {"id": 1, "text": "one"},
    ]


def test_merge_uses_last_duplicate_id_and_discards_extra_rows() -> None:
    reference: list[JsonObject] = [{"id": 1}]
    localized: list[JsonObject] = [
        {"id": 1, "text": "first"},
        {"id": 1, "text": "last"},
    ]

    assert merge_by_id(reference, localized, Path("file.json")) == [
        {"id": 1, "text": "last"}
    ]
    assert merge_by_order(reference, localized) == [{"id": 1, "text": "first"}]
    assert merge_by_order([], localized) == []


def test_cli_builds_localized_story_and_rpg_files(project: Path) -> None:
    root = project.parent
    write_json(
        root / "reference/UI.json",
        {
            "version": 2,
            "dataList": [{"id": 2, "text": "fallback"}, {"id": 1, "text": "English"}],
        },
    )
    write_json(
        root / "localize/UI.json",
        {
            "version": 1,
            "dataList": [{"id": 1, "text": "[Burn:`a`]"}, {"id": 99, "text": "extra"}],
        },
    )
    write_json(
        root / "reference/Order.json",
        {"dataList": [{"id": 1, "text": "first"}, {"id": 2, "text": "second"}]},
    )
    write_json(
        root / "localize/Order.json", {"dataList": [{"id": 20, "text": "Перевод"}]}
    )
    write_json(
        root / "reference/StoryData/chapter.json",
        {"dataList": [{"id": 0, "content": "Hello", "teller": "Dante"}]},
    )
    chapter = root / "story/chapters/chapter.txt"
    chapter.parent.mkdir()
    _ = chapter.write_text("Dante: Привет", encoding="utf-8-sig")
    write_json(
        root / "reference/RPGSystem/dialogue.json",
        {
            "dataList": [
                {
                    "key": "one",
                    "texts": [{"index": 0, "text": "English", "speaker": "Dante"}],
                }
            ]
        },
    )
    rpg_chapter = root / "story/rpg/dialogue/one.txt"
    rpg_chapter.parent.mkdir(parents=True)
    _ = rpg_chapter.write_text("Dante: Диалог", encoding="utf-8-sig")
    write_json(
        root / "reference/Untranslated.json",
        {"dataList": [{"id": 1, "text": "English"}]},
    )
    write_json(root / "reference/Empty.json", {})
    _ = (root / "localize/Empty.json").write_text(
        "Ignored invalid JSON", encoding="utf-8"
    )
    (root / "reference/directory.json").mkdir()

    main(["--config", str(project), "--output", "output"])

    output = root / "output"
    assert load_document(output / "UI.json") == {
        "version": 2,
        "dataList": [
            {"id": 2, "text": "fAllbAck"},
            {
                "id": 1,
                "text": '<sprite name="Burn"><color=#123456><u><link="Burn">A</link></u></color><style="highlight"></style>',
            },
        ],
    }
    assert load_document(output / "Order.json") == {
        "dataList": [{"id": 20, "text": "Перевод"}, {"id": 2, "text": "second"}]
    }
    assert load_document(output / "StoryData/chapter.json") == {
        "dataList": [{"id": 0, "content": "Привет", "teller": "Данте"}]
    }
    assert load_document(output / "RPGSystem/dialogue.json") == {
        "dataList": [
            {
                "key": "one",
                "texts": [{"index": 0, "text": "Диалог", "speaker": "Данте"}],
            }
        ]
    }
    for filename in ("Untranslated.json", "Empty.json"):
        assert (output / filename).read_bytes() == (
            root / "reference" / filename
        ).read_bytes()
    assert (output / "UI.json").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (output / "Font/Context/font.ttf").read_bytes() == b"font content"


def test_cli_can_reuse_reference_and_skip_fonts(project: Path) -> None:
    reference = project.parent / "cached"
    write_json(reference / "Untouched.json", {"dataList": []})
    _ = project.write_text(
        project.read_text(encoding="utf-8").replace(
            'path = "reference"', 'path = "missing"'
        ),
        encoding="utf-8",
    )
    (project.parent / "font.ttf").unlink()

    main(
        [
            "--config",
            str(project),
            "--reference",
            str(reference),
            "--output",
            "output",
            "--no-download-reference",
            "--no-include-font",
        ]
    )

    output = project.parent / "output"
    assert (output / "Untouched.json").read_bytes() == (
        reference / "Untouched.json"
    ).read_bytes()
    assert not (output / "Font").exists()


def test_cli_merges_rpg_tables_by_key(project: Path) -> None:
    root = project.parent
    _ = project.write_text(
        project.read_text().replace(
            'dialogue_files = ["RPGSystem/*.json"]',
            'dialogue_files = ["RPGSystem/dialogue.json"]',
        )
    )
    filename = "RPGSystem/rpg-loc-location-floor-1.json"
    write_json(
        root / "reference" / filename,
        {
            "dataList": [
                {"key": "2", "text": "two"},
                {"key": "1", "text": "one"},
                {"key": "3", "text": "fallback"},
            ]
        },
    )
    write_json(
        root / "localize" / filename,
        {
            "dataList": [
                {"key": "1", "text": "один"},
                {"key": "2", "text": "два"},
                {"key": "4", "text": "extra"},
            ]
        },
    )

    main(["--config", str(project), "--output", "output"])

    assert load_document(root / "output" / filename) == {
        "dataList": [
            {"key": "2", "text": "два"},
            {"key": "1", "text": "один"},
            {"key": "3", "text": "fallback"},
        ]
    }


def test_cli_applies_all_matching_highlight_rules(project: Path) -> None:
    root = project.parent
    _ = project.write_text(
        project.read_text()
        + """
[[close_highlight]]
file_pattern = "Skills.json"
path = "$.dataList[*].levelList[*].coinlist[*].coindescs[*].desc"
[[close_highlight]]
file_pattern = "Skills.json"
path = "$.dataList[*].levelList[*].desc"
"""
    )
    write_json(root / "reference/Skills.json", {"dataList": [{"id": 1}]})
    write_json(
        root / "localize/Skills.json",
        {
            "dataList": [
                {
                    "id": 1,
                    "levelList": [
                        {
                            "desc": "Skill description",
                            "coinlist": [{"coindescs": [{"desc": "Coin description"}]}],
                        }
                    ],
                }
            ]
        },
    )

    main(["--config", str(project), "--output", "output"])

    assert load_document(root / "output/Skills.json") == {
        "dataList": [
            {
                "id": 1,
                "levelList": [
                    {
                        "desc": 'Skill description<style="highlight"></style>',
                        "coinlist": [
                            {
                                "coindescs": [
                                    {
                                        "desc": 'Coin description<style="highlight"></style>'
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_config_rejects_invalid_field_types(project: Path) -> None:
    _ = project.write_text(
        project.read_text().replace(
            'order = ["StoryData/*.json", "Order.json"]', "order = 42"
        )
    )

    with pytest.raises(msgspec.ValidationError):
        _ = Config.from_file(project)


def test_config_defaults_are_independent(project: Path) -> None:
    _ = project.write_text(
        project.read_text().replace('[rpg]\ndialogue_files = ["RPGSystem/*.json"]', "")
    )
    first = Config.from_file(project)
    second = Config.from_file(project)
    first.rpg.dialogue_files.append("test.json")

    assert not second.rpg.dialogue_files
