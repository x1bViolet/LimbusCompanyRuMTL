import copy
import re
from pathlib import Path

import msgspec
from loguru import logger

from .json_data import JsonObject, object_list, string_field
from .models import StoryEntities, StoryEntity


def load_story_entities(path: Path) -> StoryEntities:
    return StoryEntities(
        teller=msgspec.json.decode(
            (path / "tellers.json").read_text(encoding="utf-8-sig"),
            type=list[StoryEntity],
        ),
        title=msgspec.json.decode(
            (path / "titles.json").read_text(encoding="utf-8-sig"),
            type=list[StoryEntity],
        ),
        place=msgspec.json.decode(
            (path / "places.json").read_text(encoding="utf-8-sig"),
            type=dict[str, str | int],
        ),
    )


def load_dialogue_translations(chapter: Path) -> list[str]:
    content = "\n".join(
        line.strip()
        for line in chapter.read_text(encoding="utf-8-sig").splitlines()
        if not line.strip().startswith("#")
    ).strip()
    if not content:
        return []

    translations: list[str] = []
    for block in re.split(r"\n{2,}", content):
        _, separator, text = block.partition(":")
        if not separator:
            raise ValueError(f"Invalid line format in {chapter}: {block}")
        translations.append(text.strip().replace("\n[KEEP_LINE]\n", "\n\n"))
    return translations


def translate_story(
    reference: JsonObject, chapter: Path, entities: StoryEntities
) -> JsonObject:
    translations = iter(load_dialogue_translations(chapter))
    result = copy.deepcopy(reference)
    for line in object_list(result["dataList"]):
        line_id = line.setdefault("id", None)
        if line.get("content") and (
            line_id is None or (isinstance(line_id, int) and line_id >= 0)
        ):
            content = next(translations, None)
            if content is None:
                raise ValueError(f"Not enough translations in {chapter}")
            line["content"] = content

        for field, candidates in (
            ("title", entities.title),
            ("teller", entities.teller),
        ):
            if not line.get(field):
                continue
            for entity in candidates:
                if entity.original == line[field] and entity.model == line.get("model"):
                    line[field] = entity.translation
                    break
            else:
                logger.warning(
                    f"Unknown {field} in {chapter}: {line[field]} ({line.get('model')})"
                )

        place = line.get("place")
        if place:
            if isinstance(place, str) and place in entities.place:
                line["place"] = entities.place[place]
            elif place != -1:
                logger.warning(f"Unknown place in {chapter}: {place}")

    if next(translations, None) is not None:
        raise ValueError(f"Too many translations in {chapter}")
    return result


def translate_rpg_speaker(speaker: str, entities: StoryEntities, chapter: Path) -> str:
    matches = [entity for entity in entities.teller if entity.original == speaker]
    for entity in matches:
        if entity.model is None:
            return entity.translation
    translations = {entity.translation for entity in matches}
    if len(translations) == 1:
        return translations.pop()
    logger.warning(f"Unknown or ambiguous speaker in {chapter}: {speaker}")
    return speaker


def create_rpg_dialogue(
    dialogue: JsonObject, chapter: Path, entities: StoryEntities
) -> None:
    blocks: list[str] = []
    for line in object_list(dialogue["texts"]):
        original = string_field(line, "text")
        comment = "# Original: " + original.replace("\n", "\n# ")
        text = original.replace("\n\n", "\n[KEEP_LINE]\n")
        speaker = (
            translate_rpg_speaker(string_field(line, "speaker"), entities, chapter)
            if line.get("speaker")
            else "Narrator"
        )
        blocks.append(f"{comment}\n{speaker}: {text}")
    chapter.parent.mkdir(parents=True, exist_ok=True)
    with chapter.open("x", encoding="utf-8-sig") as stream:
        _ = stream.write("\n\n".join(blocks) + "\n")


def translate_rpg(
    reference: JsonObject, directory: Path, entities: StoryEntities
) -> JsonObject:
    result = copy.deepcopy(reference)
    for dialogue in object_list(result["dataList"]):
        chapter = directory / f"{string_field(dialogue, 'key')}.txt"
        if not chapter.is_file():
            logger.warning(
                f"Missing translation in {chapter}; keeping English fallback"
            )
            create_rpg_dialogue(dialogue, chapter, entities)
            continue

        translations = load_dialogue_translations(chapter)
        lines = object_list(dialogue["texts"])
        if len(translations) > len(lines):
            raise ValueError(f"Too many translations in {chapter}")

        for position, line in enumerate(lines):
            if position >= len(translations) or not translations[position]:
                logger.warning(
                    "Missing translation in {} at index {}; keeping English fallback",
                    chapter,
                    line["index"],
                )
                continue
            line["text"] = translations[position]
            if line.get("speaker"):
                line["speaker"] = translate_rpg_speaker(
                    string_field(line, "speaker"), entities, chapter
                )
    return result
