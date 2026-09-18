import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import msgspec
import pytest
import requests

from scripts.assets import (
    download_included_fonts,
    download_release_asset,
    get_release_assets,
    load_replacements_map,
    prepare_reference,
)
from scripts.models import Font, IncludedFont, Reference


@dataclass
class Response:
    content: bytes
    error: requests.HTTPError | None = None

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error


@pytest.fixture
def responses(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Response]]:
    responses: dict[str, Response] = {}

    def get(url: str, *, timeout: int) -> Response:
        assert timeout > 0
        return responses.pop(url)

    get_release_assets.cache_clear()
    monkeypatch.setattr(requests, "get", get)
    yield responses
    get_release_assets.cache_clear()


def test_local_font_assets_are_loaded_and_copied(tmp_path: Path) -> None:
    replacement_map = tmp_path / "map.json"
    _ = replacement_map.write_text('{"body": {"ж": "A"}}', encoding="utf-8")
    font_file = tmp_path / "font.ttf"
    _ = font_file.write_bytes(b"font content")
    font = Font(
        str(replacement_map),
        include=[IncludedFont("Context/font.ttf", str(font_file))],
    )

    assert load_replacements_map(font) == {"body": {"ж": "A"}}
    download_included_fonts(font, tmp_path / "output")
    assert (tmp_path / "output/Context/font.ttf").read_bytes() == b"font content"


def test_invalid_replacement_map_is_rejected(tmp_path: Path) -> None:
    replacement_map = tmp_path / "map.json"
    _ = replacement_map.write_text('{"body": {"a": 123}}', encoding="utf-8")

    with pytest.raises(msgspec.ValidationError):
        _ = load_replacements_map(Font(str(replacement_map)))


def test_release_metadata_is_cached_for_multiple_assets(
    tmp_path: Path, responses: dict[str, Response]
) -> None:
    responses.update(
        {
            "https://api.github.com/repos/owner/fonts/releases/latest": Response(
                msgspec.json.encode(
                    {
                        "assets": [
                            {
                                "name": "map.json",
                                "browser_download_url": "https://assets/map",
                            },
                            {
                                "name": "font.ttf",
                                "browser_download_url": "https://assets/font",
                            },
                        ]
                    }
                )
            ),
            "https://assets/map": Response(b'{"body": {"a": "A"}}'),
            "https://assets/font": Response(b"font content"),
        }
    )
    font = Font("map.json", "owner/fonts", [IncludedFont("font.ttf", "font.ttf")])

    assert load_replacements_map(font) == {"body": {"a": "A"}}
    download_included_fonts(font, tmp_path)
    assert (tmp_path / "font.ttf").read_bytes() == b"font content"
    with pytest.raises(FileNotFoundError, match="missing.ttf"):
        _ = download_release_asset("owner/fonts", "missing.ttf")
    assert not responses


def test_download_errors_are_propagated(responses: dict[str, Response]) -> None:
    responses["https://api.github.com/repos/owner/fonts/releases/latest"] = Response(
        b"", requests.HTTPError("unavailable")
    )

    with pytest.raises(requests.HTTPError, match="unavailable"):
        _ = get_release_assets("owner/fonts")


def test_reference_archive_extracts_only_configured_subdirectory(
    tmp_path: Path, responses: dict[str, Response]
) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("reference-main/English/nested/file.json", b"{}")
        archive.writestr("reference-main/English/", b"")
        archive.writestr("reference-main/Other/file.json", b"ignored")
        archive.writestr("reference-main/English-extra/file.json", b"ignored")
    responses["https://github.com/owner/reference/archive/refs/heads/main.zip"] = (
        Response(content.getvalue())
    )

    result = prepare_reference(
        Reference("./English/", "owner/reference", "main"), tmp_path / "output"
    )

    assert result == tmp_path / "output"
    assert [path.relative_to(result) for path in result.rglob("*.json")] == [
        Path("nested/file.json")
    ]
    assert (result / "nested/file.json").read_bytes() == b"{}"


def test_reference_archive_cannot_write_outside_target(
    tmp_path: Path, responses: dict[str, Response]
) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("reference-main/../outside.json", b"{}")
    responses["https://github.com/owner/reference/archive/refs/heads/main.zip"] = (
        Response(content.getvalue())
    )

    with pytest.raises(ValueError, match="escapes reference directory"):
        _ = prepare_reference(
            Reference("", "owner/reference", "main"), tmp_path / "output"
        )
    assert not (tmp_path / "outside.json").exists()


def test_local_reference_returns_its_configured_directory(tmp_path: Path) -> None:
    assert prepare_reference(Reference(str(tmp_path)), tmp_path / "unused") == tmp_path
    with pytest.raises(FileNotFoundError):
        _ = prepare_reference(Reference(str(tmp_path / "missing")), tmp_path / "unused")
