import shlex
import sys
from pathlib import Path

import pytest

from scripts.fill_entities import main, missing_entities, write_json
from scripts.models import StoryEntities, StoryEntity
from scripts.story import load_story_entities


def test_discovery_matches_story_and_rpg_resolution(tmp_path: Path) -> None:
    story = tmp_path / "StoryData/chapter.json"
    story.parent.mkdir()
    write_json(
        story,
        {
            "dataList": [
                {"teller": "Known", "model": "new", "title": "Title", "place": "Room"},
                {"teller": "Known", "model": "new", "title": "Title", "place": "Room"},
                {"teller": "Known", "model": "old", "place": -1},
            ]
        },
    )
    rpg = tmp_path / "RPGSystem/dialogue.json"
    rpg.parent.mkdir()
    write_json(
        rpg,
        {
            "dataList": [
                {
                    "texts": [
                        {"speaker": speaker}
                        for speaker in ("Known", "Ambiguous", "New", "", "New")
                    ]
                }
            ]
        },
    )
    write_json(tmp_path / "unrelated.json", {"dataList": [{"teller": "Ignored"}]})
    known = StoryEntities(
        teller=[
            StoryEntity("Known", "Известный", "old"),
            StoryEntity("Ambiguous", "Первый", "one"),
            StoryEntity("Ambiguous", "Второй", "two"),
        ]
    )

    assert missing_entities(tmp_path, known, ["RPGSystem/*.json"]) == StoryEntities(
        teller=[
            StoryEntity("Known", "", "new"),
            StoryEntity("Ambiguous", ""),
            StoryEntity("New", ""),
        ],
        title=[StoryEntity("Title", "", "new")],
        place={"Room": ""},
    )


@pytest.mark.parametrize("invalid", [False, True])
def test_editor_round_trip_and_draft_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, invalid: bool
) -> None:
    entities = tmp_path / "entities"
    entities.mkdir()
    write_json(entities / "tellers.json", [StoryEntity("Known", "Известный")])
    write_json(entities / "titles.json", [])
    write_json(entities / "places.json", {"-1": -1})
    reference = tmp_path / "reference/StoryData"
    reference.mkdir(parents=True)
    write_json(
        reference / "chapter.json",
        {
            "dataList": [
                {"teller": "New", "title": "Skipped", "place": "Room"},
            ]
        },
    )
    editor = tmp_path / "fake editor.py"
    _ = editor.write_text(
        "import json, pathlib, sys\n"
        + "path = pathlib.Path(sys.argv[1])\n"
        + "data = json.loads(path.read_text(encoding='utf-8-sig'))\n"
        + "data['teller'][0]['translation'] = 'Новый'\n"
        + "data['place']['Room'] = 'Комната'\n"
        + ("data['title'][0]['original'] = 'Wrong'\n" if invalid else "")
        + "path.write_text(json.dumps(data), encoding='utf-8')\n"
    )
    monkeypatch.setenv("EDITOR", shlex.join([sys.executable, str(editor)]))
    draft = tmp_path / "draft.json"
    args = [
        "--reference",
        str(reference.parent),
        "--entities",
        str(entities),
        "--draft",
        str(draft),
    ]
    before = {path: path.read_bytes() for path in entities.iterdir()}
    if invalid:
        with pytest.raises(ValueError, match="Unknown or duplicate"):
            main(args)
        assert draft.exists()
        assert all(path.read_bytes() == content for path, content in before.items())
        # Recover the same draft on the next invocation.
        _ = editor.write_text(
            "import pathlib, sys\n"
            + "path = pathlib.Path(sys.argv[1])\n"
            + "path.write_text(path.read_text().replace('Wrong', 'Skipped'))\n"
        )
    main(args)
    assert not draft.exists()
    assert load_story_entities(entities) == StoryEntities(
        teller=[StoryEntity("Known", "Известный"), StoryEntity("New", "Новый")],
        place={"-1": -1, "Room": "Комната"},
    )
    assert (entities / "titles.json").read_bytes() == before[entities / "titles.json"]
