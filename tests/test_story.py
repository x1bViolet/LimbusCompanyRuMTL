import copy
from pathlib import Path

import pytest

from scripts.json_data import JsonObject, object_list
from scripts.models import StoryEntities, StoryEntity
from scripts.story import (
    create_rpg_dialogue,
    load_dialogue_translations,
    load_story_entities,
    translate_rpg,
    translate_rpg_speaker,
    translate_story,
)


def test_dialogue_parser_handles_comments_bom_and_blank_lines(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.txt"
    _ = chapter.write_text(
        "# comment\nDante: First: line\n[KEEP_LINE]\nNext line\n\nNarrator: Last",
        encoding="utf-8-sig",
    )

    assert load_dialogue_translations(chapter) == [
        "First: line\n\nNext line",
        "Last",
    ]


def test_story_translates_content_and_entities_without_changing_reference(
    tmp_path: Path,
) -> None:
    chapter = tmp_path / "chapter.txt"
    _ = chapter.write_text("Dante: Привет", encoding="utf-8")
    reference: JsonObject = {
        "dataList": [
            {"content": "Hello", "teller": "Dante", "model": "dante", "place": "Bus"},
            {"id": -1, "content": "Direction"},
        ],
        "metadata": {"keep": True},
    }
    original = copy.deepcopy(reference)
    entities = StoryEntities(
        teller=[StoryEntity("Dante", "Данте", "dante")],
        place={"Bus": "Автобус"},
    )

    translated = translate_story(reference, chapter, entities)

    assert translated["dataList"] == [
        {
            "content": "Привет",
            "teller": "Данте",
            "model": "dante",
            "place": "Автобус",
            "id": None,
        },
        {"id": -1, "content": "Direction"},
    ]
    assert translated["metadata"] == {"keep": True}
    assert reference == original


@pytest.mark.parametrize("translation", ["", "Dante: One\n\nDante: Two"])
def test_story_rejects_translation_count_mismatch(
    tmp_path: Path, translation: str
) -> None:
    chapter = tmp_path / "chapter.txt"
    _ = chapter.write_text(translation, encoding="utf-8")
    reference: JsonObject = {"dataList": [{"id": 1, "content": "Hello"}]}

    with pytest.raises(ValueError, match="translations"):
        _ = translate_story(reference, chapter, StoryEntities())


def test_rpg_keeps_missing_lines_and_creates_missing_chapters(tmp_path: Path) -> None:
    _ = (tmp_path / "existing.txt").write_text("Dante: Привет", encoding="utf-8")
    reference: JsonObject = {
        "dataList": [
            {
                "key": "existing",
                "texts": [
                    {"index": 7, "text": "Hello", "speaker": "Dante"},
                    {"index": 9, "text": "Fallback", "speaker": "Dante"},
                ],
            },
            {"key": "missing", "texts": [{"index": 0, "text": "First\n\nLast"}]},
        ]
    }
    original = copy.deepcopy(reference)
    entities = StoryEntities(teller=[StoryEntity("Dante", "Данте")])

    translated = translate_rpg(reference, tmp_path, entities)

    rows = object_list(translated["dataList"])
    assert rows[0]["texts"] == [
        {"index": 7, "text": "Привет", "speaker": "Данте"},
        {"index": 9, "text": "Fallback", "speaker": "Dante"},
    ]
    assert rows[1] == object_list(reference["dataList"])[1]
    assert reference == original
    assert load_dialogue_translations(tmp_path / "missing.txt") == ["First\n\nLast"]


def test_invalid_dialogue_block_reports_chapter(tmp_path: Path) -> None:
    chapter = tmp_path / "broken.txt"
    _ = chapter.write_text("Missing speaker separator", encoding="utf-8")

    with pytest.raises(ValueError, match="broken.txt"):
        _ = load_dialogue_translations(chapter)


@pytest.mark.parametrize(
    ("tellers", "expected"),
    [
        (
            [StoryEntity("Dante", "Model", "model"), StoryEntity("Dante", "Данте")],
            "Данте",
        ),
        (
            [StoryEntity("Dante", "Данте", "a"), StoryEntity("Dante", "Данте", "b")],
            "Данте",
        ),
        ([StoryEntity("Dante", "One", "a"), StoryEntity("Dante", "Two", "b")], "Dante"),
        ([], "Dante"),
    ],
)
def test_rpg_speaker_prefers_model_free_or_unambiguous_translation(
    tellers: list[StoryEntity], expected: str
) -> None:
    assert (
        translate_rpg_speaker(
            "Dante", StoryEntities(teller=tellers), Path("chapter.txt")
        )
        == expected
    )


def test_rpg_empty_translations_keep_the_original_line(tmp_path: Path) -> None:
    _ = (tmp_path / "chapter.txt").write_text("Dante:", encoding="utf-8")
    reference: JsonObject = {
        "dataList": [
            {
                "key": "chapter",
                "texts": [{"index": 0, "text": "English", "speaker": "Dante"}],
            }
        ]
    }

    assert translate_rpg(reference, tmp_path, StoryEntities()) == reference


def test_rpg_rejects_extra_translations(tmp_path: Path) -> None:
    _ = (tmp_path / "chapter.txt").write_text("Narrator: Extra", encoding="utf-8")
    reference: JsonObject = {"dataList": [{"key": "chapter", "texts": []}]}

    with pytest.raises(ValueError, match="Too many translations"):
        _ = translate_rpg(reference, tmp_path, StoryEntities())


def test_rpg_template_never_overwrites_an_existing_translation(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.txt"
    _ = chapter.write_text("Existing translation", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_rpg_dialogue({"texts": []}, chapter, StoryEntities())
    assert chapter.read_text(encoding="utf-8") == "Existing translation"


def test_story_entities_support_bom_and_no_place_sentinel(tmp_path: Path) -> None:
    _ = (tmp_path / "tellers.json").write_text(
        '[{"original": "Dante", "translation": "Данте"}]', encoding="utf-8-sig"
    )
    _ = (tmp_path / "titles.json").write_text("[]", encoding="utf-8-sig")
    _ = (tmp_path / "places.json").write_text('{"-1": -1}', encoding="utf-8-sig")

    entities = load_story_entities(tmp_path)

    assert entities.teller == [StoryEntity("Dante", "Данте")]
    assert entities.place == {"-1": -1}
