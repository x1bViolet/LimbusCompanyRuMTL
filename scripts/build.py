import requests
import zipfile
import io
import re
import collections
import json
import shutil
import fnmatch
import copy
import argparse
import bisect

from itertools import zip_longest
from pathlib import Path
from jsonpath_ng.ext import parse
from loguru import logger

from .models import Config, FontRule, ReplacementMap, Reference, XmlEscape


def prepare_reference(reference: Reference, target_path: Path) -> None:
    if reference.repo is None:
        reference_path = Path(reference.path)
        if not reference_path.exists():
            raise FileNotFoundError(f"Reference path {reference_path} does not exist")
        return reference_path

    logger.info(f"Downloading reference from {reference.repo}...")
    response = requests.get(
        f"https://github.com/{reference.repo}/archive/refs/heads/{reference.branch}.zip"
    )
    response.raise_for_status()

    content = io.BytesIO(response.content)

    target_path.mkdir(parents=True, exist_ok=True)
    prefix = reference.path[2:] if reference.path.startswith("./") else reference.path
    repo_name = reference.repo.split("/")[-1]
    prefix = f"{repo_name}-{reference.branch}/{prefix}"

    if not prefix.endswith("/"):
        prefix += "/"

    with zipfile.ZipFile(content, "r") as z:
        for file in z.namelist():
            if file.endswith("/") or not file.startswith(prefix):
                continue

            relative_path = file[len(prefix) :]
            result_path = target_path / relative_path
            result_path.parent.mkdir(parents=True, exist_ok=True)

            with z.open(file) as source, result_path.open("wb") as target:
                target.write(source.read())

    logger.info(f"Reference saved to {target_path}")


def load_replacements_map(
    replacements_map: ReplacementMap,
) -> dict[str, dict[str, str]]:
    if replacements_map.repo is None:
        with open(replacements_map.path, "r", encoding="utf-8") as f:
            return json.load(f)

    response = requests.get(
        f"https://api.github.com/repos/{replacements_map.repo}/releases/latest"
    )
    response.raise_for_status()
    release_data = response.json()
    release_assets = release_data["assets"]

    for asset in release_assets:
        if asset["name"] != replacements_map.path:
            continue

        logger.info(f"Downloading replacement map from {asset['browser_download_url']}")
        response = requests.get(asset["browser_download_url"])
        response.raise_for_status()
        return response.json()

    raise FileNotFoundError(
        f"Replacement map '{replacements_map.path}' not found in latest release of '{replacements_map.repo}'"
    )


def load_keyword_colors() -> dict[str, str]:
    keyword_colors_path = Path("./data/build/keyword_colors.txt")
    if not keyword_colors_path.exists():
        raise FileNotFoundError(
            f"Keyword colors file {keyword_colors_path} does not exist"
        )

    with open(keyword_colors_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = {}
    for line in lines:
        line = line.strip()
        if line == "":
            continue

        keyword_id, color = line.split(" ¤ ")
        result[keyword_id] = color

    return result


def escape_keyword_text(text: str) -> str:
    escape_keyword = "[TabExplain]"

    return " ".join(
        word + escape_keyword if not word.endswith(escape_keyword) and word.strip() else word
        for word in text.split(" ")
    )


def replace_shorthands(
    text: str, keyword_colors: dict[str, str], keyword_regex: re.Pattern
) -> str:
    def make_replacement(match: re.Match) -> str:
        keyword_id = match.group("keyword_id")
        text = match.group("text")

        if match.group("color") is not None:
            color = match.group("color")
        elif keyword_id in keyword_colors:
            color = keyword_colors[keyword_id]
        else:
            logger.debug(f"Unknown keyword ID: {keyword_id}!")
            color = "#f8c200"

        return (
            f'<sprite name="{keyword_id}">'
            f"<color={color}>"
            f"<u>"
            f'<link="{keyword_id}">'
            f"{escape_keyword_text(text)}"
            f"</link>"
            f"</u>"
            f"</color>"
        )

    return keyword_regex.sub(make_replacement, text)


def convert_keywords(
    data: collections.OrderedDict | list,
    keyword_colors: dict[str, str],
    keyword_regex: re.Pattern,
) -> None:
    if isinstance(data, collections.OrderedDict):
        items = data.items()
    else:
        items = enumerate(data)

    for key, value in items:
        if isinstance(value, (collections.OrderedDict, list)):
            convert_keywords(value, keyword_colors, keyword_regex)
        elif isinstance(value, str):
            data[key] = replace_shorthands(value, keyword_colors, keyword_regex)


def is_in_range(pos: int, ranges: list[tuple[int, int]]) -> bool:
    if not ranges:
        return False

    index = bisect.bisect_left(ranges, (pos + 1,)) - 1
    if index >= 0 and ranges[index][0] <= pos <= ranges[index][1]:
        return True

    return False


def get_markup_positions(
    text: str,
    singular_keywords: list[str],
    escape_short: bool = True,
    escape_keywords: bool = True,
) -> list[tuple[int, int]]:
    if not escape_keywords:
        return []

    keyword_regex = re.compile(r"<(?P<keyword_id>[A-z]+)[^>]*>")
    keyword_short = re.compile(r"\[(?P<keyword_id>[A-z]+)\]")
    to_escape = []

    for match in keyword_regex.finditer(text):
        keyword_id = match.group("keyword_id")
        if keyword_id.lower() in singular_keywords:
            to_escape.append((match.start(), match.end() - 1))
            continue

        close_tag = re.compile(rf"</{re.escape(keyword_id)}\s*>")
        if close_tags := list(close_tag.finditer(text, match.end())):
            to_escape.append((match.start(), match.end() - 1))
            to_escape.extend((tag.start(), tag.end() - 1) for tag in close_tags)

    if escape_short:
        for match in keyword_short.finditer(text):
            to_escape.append((match.start(), match.end() - 1))

    if not to_escape:
        return []

    to_escape.sort(key=lambda x: x[0])

    merged = []
    current_start, current_end = to_escape[0]

    for next_start, next_end in to_escape[1:]:
        if next_start <= current_end + 1:
            current_end = max(current_end, next_end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end

    merged.append((current_start, current_end))
    return merged


def apply_font_rule(
    data: collections.OrderedDict,
    rule: FontRule,
    replacements: dict[str, str],
    singular_keywords: list[str],
) -> None:
    def do_update(value: str, *_) -> str:
        markup_positions = get_markup_positions(
            value, singular_keywords, rule.escape_short_keywords, rule.escape_keywords
        )

        result = ""
        for i, char in enumerate(value):
            if is_in_range(i, markup_positions) or char not in replacements:
                result += char
            else:
                result += replacements[char]
        return result

    parse(rule.path).update(data, do_update)


def apply_font_rules(
    data: collections.OrderedDict,
    rules: list[FontRule],
    replacements_map: dict[str, dict[str, str]],
    xml_escape: XmlEscape,
) -> None:
    for rule in rules:
        if rule.font not in replacements_map:
            logger.warning(f"Font {rule.font} not found in replacements map!")
            continue

        apply_font_rule(
            data,
            rule,
            replacements_map[rule.font],
            xml_escape.singular_keywords,
        )


def merge_by_id(
    reference: list[dict],
    localize: list[dict],
    file: Path,
) -> list[dict]:
    by_id = {}

    for loc in localize:
        loc_id = loc.get("id")
        by_id[loc_id] = loc

    if len(by_id) != len(localize):
        logger.debug(f"Duplicate ID in {file}!!!")

    unknown_ids = []
    result = []

    for ref in reference:
        ref_id = ref.get("id")
        if ref_id in by_id:
            result.append(by_id[ref_id])
        else:
            unknown_ids.append(ref_id)
            result.append(ref)

    if unknown_ids:
        logger.debug(f"Unknown IDs in {file}: {unknown_ids}")

    return result


def merge_by_order(
    reference: list[dict],
    localize: list[dict],
    file: Path,
) -> list[dict]:
    result = []

    for ref, loc in zip_longest(reference, localize, fillvalue=None):
        if ref is None:
            break

        if loc is None:
            result.append(ref)
        else:
            result.append(loc)

    if len(result) != len(reference):
        logger.warning(f"Size mismatch in {file}!!!")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="./config.toml")
    parser.add_argument("--output", type=str, default="./dist/localize")
    parser.add_argument("--reference", type=str, default="./.reference")
    parser.add_argument("--no-download-reference", action="store_true", default=False)

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file {config_path} does not exist")

    config = Config.from_file(config_path)

    replacements_map = load_replacements_map(config.replacement_map)

    reference_path = Path(args.reference)
    if not args.no_download_reference:
        prepare_reference(config.reference, reference_path)

    keyword_colors = load_keyword_colors()

    dist_path = Path("./dist/localize")
    dist_path.mkdir(parents=True, exist_ok=True)

    localization_path = Path("./localize")
    for file in reference_path.glob("**/*.json"):
        if not file.is_file():
            continue

        relative_path = file.relative_to(reference_path)
        corresponding_file = localization_path / relative_path
        dist_file = dist_path / relative_path

        dist_file.parent.mkdir(parents=True, exist_ok=True)
        if not corresponding_file.exists():
            shutil.copy(file, dist_file)
            continue

        # print(f"Processing {file}")
        reference = json.loads(
            file.read_text(encoding="utf-8-sig"),
            object_pairs_hook=collections.OrderedDict,
        )
        localize = json.loads(
            corresponding_file.read_text(encoding="utf-8-sig"),
            object_pairs_hook=collections.OrderedDict,
        )

        if len(reference) == 0:
            shutil.copy(file, dist_file)
            continue

        for file_pattern in config.keyword_shorthands.apply_for:
            if not fnmatch.fnmatch(relative_path.as_posix(), file_pattern):
                continue

            convert_keywords(
                localize,
                keyword_colors,
                re.compile(config.keyword_shorthands.regex),
            )

            break

        for file_pattern, rules in config.font_rules.items():
            if not fnmatch.fnmatch(relative_path.as_posix(), file_pattern):
                continue

            apply_font_rules(
                localize,
                rules,
                replacements_map,
                config.xml_escape,
            )

        data_reference = reference["dataList"]
        data_localize = localize["dataList"]

        is_order_priority = any(
            fnmatch.fnmatch(relative_path.as_posix(), pattern)
            for pattern in config.priority.order
        )

        if is_order_priority:
            result = merge_by_order(data_reference, data_localize, dist_file)
        else:
            result = merge_by_id(data_reference, data_localize, dist_file)

        result = {
            **copy.deepcopy(reference),
            "dataList": result,
        }

        with open(dist_file, "w", encoding="utf-8-sig") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
