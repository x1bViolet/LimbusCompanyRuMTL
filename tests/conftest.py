import re
from pathlib import Path

import pytest

from scripts.models import Config


@pytest.fixture
def keyword_regex() -> re.Pattern[str]:
    config = Config.from_file(Path(__file__).parents[1] / "config.toml")
    return re.compile(config.keyword_shorthands.regex)
