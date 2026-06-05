from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "scout" / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def fixtures_dir_writer() -> Path:
    return Path(__file__).parent / "writer" / "fixtures"
