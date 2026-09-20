import io
import shutil
import zipfile
from functools import cache
from pathlib import Path

import msgspec
import requests
from loguru import logger

from .models import Font, Reference, Release, ReleaseAsset

type ReplacementsMap = dict[str, dict[str, str]]


def download(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def prepare_reference(reference: Reference, target_path: Path) -> Path:
    if reference.repo is None:
        reference_path = Path(reference.path)
        if not reference_path.is_dir():
            raise FileNotFoundError(f"Reference path {reference_path} does not exist")
        return reference_path
    if reference.branch is None:
        raise ValueError("A branch is required for a remote reference")

    logger.info(f"Downloading reference from {reference.repo}...")
    content = download(
        f"https://github.com/{reference.repo}/archive/refs/heads/{reference.branch}.zip"
    )
    repo_name = reference.repo.rsplit("/", 1)[-1]
    subdirectory = reference.path.removeprefix("./").strip("/")
    prefix = f"{repo_name}-{reference.branch}/"
    if subdirectory:
        prefix += f"{subdirectory}/"

    target_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            result_path = target_path / member.filename.removeprefix(prefix)
            if not result_path.resolve().is_relative_to(target_path.resolve()):
                raise ValueError(
                    f"Archive path escapes reference directory: {member.filename}"
                )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            _ = result_path.write_bytes(archive.read(member))

    logger.info(f"Reference saved to {target_path}")
    return target_path


@cache
def get_release_assets(repo: str) -> list[ReleaseAsset]:
    content = download(f"https://api.github.com/repos/{repo}/releases/latest")
    return msgspec.json.decode(content, type=Release).assets


def download_release_asset(repo: str, filename: str) -> bytes:
    for asset in get_release_assets(repo):
        if asset.name == filename:
            return download(asset.browser_download_url)
    raise FileNotFoundError(
        f"Asset '{filename}' not found in latest release of '{repo}'"
    )


def load_replacements_map(font: Font) -> ReplacementsMap:
    content = (
        Path(font.replacement_map_path).read_bytes()
        if font.repo is None
        else download_release_asset(font.repo, font.replacement_map_path)
    )
    return msgspec.json.decode(content, type=dict[str, dict[str, str]])


def download_included_fonts(font: Font, target_path: Path) -> None:
    for included_font in font.include:
        result_path = target_path / included_font.path
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if font.repo is None:
            _ = shutil.copyfile(included_font.filename, result_path)
        else:
            _ = result_path.write_bytes(
                download_release_asset(font.repo, included_font.filename)
            )


def load_keyword_colors(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keyword_id, color = line.strip().split(" ¤ ")
            result[keyword_id] = color
    return result
