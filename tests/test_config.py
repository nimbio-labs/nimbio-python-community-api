import pytest

from nimbio_community_api import AsyncNimbioClient, NimbioClient, NimbioConfigError


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("NIMBIO_API_KEY", raising=False)
    with pytest.raises(NimbioConfigError):
        NimbioClient()


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("NIMBIO_API_KEY", "nimbio_test_xxxxxxxxxxxxxxxxxxxxxx")
    client = NimbioClient()
    assert client.mode == "test"
    client.close()


def test_environment_base_urls(test_key):
    assert NimbioClient(test_key, environment="prod").base_url == "https://api.nimbio.com"
    assert NimbioClient(test_key, environment="dev").base_url == "https://api.nimbio.dev"
    assert NimbioClient(test_key, environment="local").base_url == "http://localhost:8000"


def test_base_url_override_wins(test_key):
    c = NimbioClient(test_key, environment="prod", base_url="https://example.test/")
    assert c.base_url == "https://example.test"  # trailing slash stripped


def test_unknown_environment_raises(test_key):
    with pytest.raises(NimbioConfigError):
        NimbioClient(test_key, environment="staging")


def test_mode_detection(test_key, live_key):
    assert NimbioClient(test_key).mode == "test"
    assert NimbioClient(live_key).mode == "live"
    assert NimbioClient("weird_prefix_key").mode is None


def test_env_var_environment(monkeypatch, test_key):
    monkeypatch.setenv("NIMBIO_ENV", "dev")
    assert NimbioClient(test_key).base_url == "https://api.nimbio.dev"


def test_async_client_constructs(test_key):
    c = AsyncNimbioClient(test_key, environment="dev")
    assert c.base_url == "https://api.nimbio.dev"
    assert c.mode == "test"
