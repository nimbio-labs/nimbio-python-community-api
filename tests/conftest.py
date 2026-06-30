import pytest

PROD = "https://api.nimbio.com"
TEST_KEY = "nimbio_test_abcdefghijklmnopqrstuv"
LIVE_KEY = "nimbio_live_abcdefghijklmnopqrstuv"


@pytest.fixture
def test_key() -> str:
    return TEST_KEY


@pytest.fixture
def live_key() -> str:
    return LIVE_KEY
