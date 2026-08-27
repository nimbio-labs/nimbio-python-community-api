"""The checked-in `surface.json` must always match the endpoint registry.

A cross-repo parity checker diffs that file against the public API's OpenAPI
spec, so a stale copy is worse than none. Regenerate it with:

    UPDATE_SURFACE=1 pytest tests/test_surface.py
"""

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "emit_surface", REPO_ROOT / "scripts" / "emit_surface.py"
)
assert _spec is not None and _spec.loader is not None
emit_surface = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emit_surface)


def test_surface_json_is_current():
    rendered = emit_surface.render_surface()
    if os.environ.get("UPDATE_SURFACE"):
        emit_surface.write_surface()
        pytest.skip("UPDATE_SURFACE set — surface.json rewritten")
    on_disk = emit_surface.SURFACE_PATH.read_text(encoding="utf-8")
    assert on_disk == rendered, (
        "surface.json is stale — regenerate it with "
        "`UPDATE_SURFACE=1 pytest tests/test_surface.py`"
    )


def test_surface_covers_the_whole_registry():
    surface = emit_surface.build_surface()
    from nimbio_community_api._base import endpoints

    builders = {
        name for name, attr in vars(endpoints).items()
        if isinstance(attr, staticmethod)
    }
    # Every registry builder, plus the one hand-merged non-registry entry.
    assert {e["builder"] for e in surface["endpoints"]} == builders | {"_sse.stream"}
    assert len(surface["endpoints"]) == len(builders) + 1


def test_stream_path_tracks_the_sdk_constant():
    """The stream entry must be read from `_sse`, not hardcoded here."""
    from nimbio_community_api import _sse

    by_builder = {
        e["builder"]: (e["method"], e["path"])
        for e in emit_surface.build_surface()["endpoints"]
    }
    assert by_builder["_sse.stream"] == ("GET", _sse.STREAM_PATH)
    assert by_builder["_sse.stream"][1] == "/v1/events/stream"


def test_path_parameters_render_as_named_placeholders():
    by_builder = {
        e["builder"]: (e["method"], e["path"])
        for e in emit_surface.build_surface()["endpoints"]
    }
    assert by_builder["health"] == ("GET", "/healthz")
    assert by_builder["account_open"] == (
        "POST", "/v1/account/keys/{key_id}/latches/{latch_id}/open")
    assert by_builder["member_access_logs"] == (
        "GET", "/v1/community/members/{account_community_id}/access-logs")
    assert by_builder["remove_hold_open_event"] == (
        "DELETE",
        "/v1/community/latches/{latch_id}/hold-open/events/{event_id}")
    # Builder that iterates a body collection — the fallback cascade must still
    # leave the path parameter as a placeholder.
    assert by_builder["set_key_schedule"] == (
        "PUT", "/v1/community/keys/{key_id}/schedule")


def test_unrenderable_builder_fails_loudly():
    def wedged(key_id):
        raise TypeError("nope")

    with pytest.raises(emit_surface.SurfaceError, match="wedged"):
        emit_surface._endpoint("wedged", wedged)
