import argparse
import os
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import msgspec

from .build import matches_any
from .json_data import load_document, object_list, string_field
from .models import Config, StoryEntities, StoryEntity
from .story import load_story_entities


def entity_key(entity: StoryEntity) -> tuple[str, str | None]:
    return entity.original, entity.model


def missing_entities(
    reference: Path, entities: StoryEntities, rpg_patterns: Sequence[str]
) -> StoryEntities:
    if not reference.is_dir():
        raise FileNotFoundError(f"Reference directory not found: {reference}")
    missing = StoryEntities()
    speakers: set[str] = set()
    for source in sorted(reference.rglob("*.json")):
        relative = source.relative_to(reference)
        is_rpg = matches_any(relative, rpg_patterns)
        if relative.parts[0] != "StoryData" and not is_rpg:
            continue
        document = load_document(source)
        if not document:
            continue
        for line in object_list(document["dataList"]):
            if is_rpg:
                speakers.update(
                    string_field(text, "speaker")
                    for text in object_list(line["texts"])
                    if text.get("speaker")
                )
                continue
            model = line.get("model")
            if model is not None and not isinstance(model, str):
                raise ValueError(f"Invalid model in {source}: {model}")
            for field, known, pending in (
                ("teller", entities.teller, missing.teller),
                ("title", entities.title, missing.title),
            ):
                if line.get(field):
                    entity = StoryEntity(string_field(line, field), "", model)
                    if not any(
                        entity_key(candidate) == entity_key(entity)
                        for candidate in (*known, *pending)
                    ):
                        pending.append(entity)
            place = line.get("place")
            if isinstance(place, str) and place and place not in entities.place:
                missing.place[place] = ""

    for speaker in sorted(speakers):
        matches = [entity for entity in entities.teller if entity.original == speaker]
        if any(entity.model is None for entity in matches):
            continue
        if len({entity.translation for entity in matches}) == 1:
            continue
        if not any(
            entity.original == speaker and entity.model is None
            for entity in missing.teller
        ):
            missing.teller.append(StoryEntity(speaker, ""))
    return missing


def merge_translations(
    entities: StoryEntities, missing: StoryEntities, edited: StoryEntities
) -> StoryEntities:
    """Validate the entire draft before allowing any entity files to change."""
    result = msgspec.structs.replace(
        entities,
        teller=list(entities.teller),
        title=list(entities.title),
        place=dict(entities.place),
    )
    for pending, entries, target in (
        (missing.teller, edited.teller, result.teller),
        (missing.title, edited.title, result.title),
    ):
        allowed = {entity_key(entity) for entity in pending}
        seen: set[tuple[str, str | None]] = set()
        for entity in entries:
            key = entity_key(entity)
            if key not in allowed or key in seen:
                raise ValueError(f"Unknown or duplicate entity in draft: {key}")
            seen.add(key)
            if entity.translation.strip():
                target.append(entity)
    for original, translation in edited.place.items():
        if original not in missing.place:
            raise ValueError(f"Unknown place in draft: {original}")
        if not isinstance(translation, str):
            raise ValueError(f"Expected a translation string for place: {original}")
        if translation.strip():
            result.place[original] = translation
    return result


def write_json(path: Path, value: object) -> None:
    content = msgspec.json.format(msgspec.json.encode(value), indent=2)
    _ = path.write_text(content.decode() + "\n", encoding="utf-8-sig")


@dataclass
class Arguments(argparse.Namespace):
    config: Path = Path("config.toml")
    reference: Path = Path(".reference")
    entities: Path = Path("story/entities")
    draft: Path = Path("missing-entities.json")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Use an editor that waits, e.g. EDITOR='code --wait'. "
            + "Fill translation strings and place values; keep originals and models. "
            + "Blanks are skipped. Failed drafts are preserved for the next run. "
            + "Remove or rename a stale draft to regenerate it."
        ),
    )
    args = Arguments()
    for name, help_text in (
        ("config", "Build configuration (default: config.toml)"),
        ("reference", "Existing English reference directory (default: .reference)"),
        ("entities", "Entity directory (default: story/entities)"),
        ("draft", "Editable JSON draft (default: missing-entities.json)"),
    ):
        _ = parser.add_argument(f"--{name}", type=Path, help=help_text)
    args = parser.parse_args(argv, namespace=args)
    config = Config.from_file(args.config)
    entities = load_story_entities(args.entities)
    missing = missing_entities(args.reference, entities, config.rpg.dialogue_files)
    if not (missing.teller or missing.title or missing.place):
        print("No missing entities.")
        return
    editor = shlex.split(os.environ.get("EDITOR", ""))
    if not editor:
        parser.error("Set $EDITOR to an editor command (for example, 'code --wait').")
    if not args.draft.exists():
        write_json(args.draft, missing)
    print(f"Fill translations in {args.draft}; leave blanks to skip.", flush=True)
    _ = subprocess.run([*editor, str(args.draft.resolve())], check=True)
    edited = msgspec.json.decode(
        args.draft.read_text(encoding="utf-8-sig"), type=StoryEntities
    )
    result = merge_translations(entities, missing, edited)
    for name, before, after in (
        ("tellers", entities.teller, result.teller),
        ("titles", entities.title, result.title),
        ("places", entities.place, result.place),
    ):
        if before != after:
            write_json(args.entities / f"{name}.json", after)
    args.draft.unlink()
    print("Saved translations. Run again to fill any remaining entries.")


if __name__ == "__main__":
    main()
