"""Emit a machine-readable description of this SDK's HTTP surface.

The `endpoints` registry in `_base.py` is the single source of truth for the
wire contract, but it is Python: a cross-repo parity checker cannot diff it
against the public API's OpenAPI spec directly. This module introspects the
registry and renders `surface.json` at the repo root — method + path + builder
name for every endpoint — so the two can be compared mechanically.

Run it directly (`python scripts/emit_surface.py`) to rewrite the file, or let
`tests/test_surface.py` assert the checked-in copy is current.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = REPO_ROOT / "surface.json"


class SurfaceError(RuntimeError):
    """A builder in the registry could not be rendered into a method+path."""


def _builders() -> List[Tuple[str, Any]]:
    """Every endpoint builder in the registry, as (name, function)."""
    from nimbio_community_api._base import endpoints

    return [
        (name, attr.__func__)
        for name, attr in vars(endpoints).items()
        if isinstance(attr, staticmethod)
    ]


def _required(func: Any) -> List[str]:
    sig = inspect.signature(func)
    return [
        name
        for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
    ]


def _render(func: Any, blanked: Set[str]) -> Tuple[str, str]:
    """Call `func` with sentinel arguments and return its (method, path).

    Every required parameter is passed the literal string ``"{name}"`` so path
    parameters render as their own placeholders; parameters named in `blanked`
    get an empty list instead, which is how a body collection a builder
    iterates over is satisfied. Optional parameters keep their defaults.
    """
    kwargs: Dict[str, Any] = {}
    for name, p in inspect.signature(func).parameters.items():
        if p.default is not inspect.Parameter.empty:
            kwargs[name] = p.default
        elif name in blanked:
            kwargs[name] = []
        else:
            kwargs[name] = "{" + name + "}"

    method, path = func(**kwargs)[:2]
    # The registry percent-encodes interpolated values, sentinel braces included.
    path = unquote(path)
    if "[]" in path:
        # A blanked parameter was a path parameter, not a body one — this
        # attempt would silently corrupt the path, so reject it and let the
        # caller try a different substitution.
        raise SurfaceError(f"blanked parameter leaked into the path: {path}")
    return str(method).upper(), path


def _substitutions(required: Iterable[str]) -> Iterable[Set[str]]:
    """Sets of parameters to blank, cheapest first.

    Nothing blanked, then each required parameter alone, then growing
    cumulative prefixes for builders that iterate more than one collection.
    """
    names = list(required)
    yield set()
    for name in names:
        yield {name}
    for i in range(2, len(names) + 1):
        yield set(names[:i])


def _endpoint(name: str, func: Any) -> Dict[str, str]:
    failures: List[str] = []
    for blanked in _substitutions(_required(func)):
        try:
            method, path = _render(func, blanked)
        except Exception as e:  # noqa: BLE001 - any builder failure is a retry
            failures.append(f"{sorted(blanked) or 'no substitution'}: {e!r}")
            continue
        return {"method": method, "path": path, "builder": name}

    raise SurfaceError(
        f"could not render endpoint builder {name!r} into a method and path. "
        "Attempts:\n  " + "\n  ".join(failures)
    )


def _stream_endpoint() -> Dict[str, str]:
    """The SSE event stream, which the `endpoints` registry does not describe.

    This is a real, documented operation both SDKs implement, but it is a
    long-lived streaming GET rather than a request/response pair, so it lives
    in `_sse.py` instead of the registry. Registry introspection alone would
    miss it and the parity checker would then report a permanent one-endpoint
    gap against the OpenAPI spec that no work could ever close. The path is
    read from the SDK's own constant so this file follows if the route moves.
    """
    from nimbio_community_api import _sse

    return {"method": "GET", "path": _sse.STREAM_PATH, "builder": "_sse.stream"}


def build_surface() -> Dict[str, Any]:
    """The full surface document, ready to serialize."""
    from nimbio_community_api._version import __version__

    endpoints = [_endpoint(name, func) for name, func in _builders()]
    endpoints.append(_stream_endpoint())
    endpoints.sort(key=lambda e: (e["path"], e["method"]))
    return {
        "sdk": "python",
        "package": "nimbio-community-api",
        "version": __version__,
        "endpoints": endpoints,
    }


def render_surface() -> str:
    """The surface document as it is written to disk, trailing newline included."""
    return json.dumps(build_surface(), indent=2, sort_keys=False) + "\n"


def write_surface() -> Path:
    SURFACE_PATH.write_text(render_surface(), encoding="utf-8")
    return SURFACE_PATH


if __name__ == "__main__":
    print(f"wrote {write_surface()}")
