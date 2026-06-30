"""Exception hierarchy for the Nimbio community API client.

Every non-2xx response from the API carries a uniform error envelope::

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

These exceptions surface that envelope as typed Python errors. Catch the base
:class:`NimbioError` to handle everything, :class:`APIError` for any HTTP-level
error, or a specific subclass (e.g. :class:`RateLimitError`) for fine control.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


class NimbioError(Exception):
    """Base class for every error raised by this library."""


class NimbioConfigError(NimbioError):
    """Raised for client misconfiguration (e.g. a missing API key)."""


class APIConnectionError(NimbioError):
    """The request never produced an HTTP response (DNS, TCP, TLS failure)."""

    def __init__(self, message: str = "Could not reach the Nimbio API", *,
                 cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class APITimeoutError(APIConnectionError):
    """The request timed out before a response was received."""

    def __init__(self, message: str = "The request to the Nimbio API timed out",
                 *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message, cause=cause)


class APIError(NimbioError):
    """An HTTP error response (status >= 400) with the parsed error envelope.

    Attributes:
        status_code: HTTP status code.
        code:        Machine-readable ``error.code`` from the envelope.
        message:     Human-readable ``error.message``.
        request_id:  Server-assigned id — quote it in support requests.
        response:    The raw decoded JSON body (may be ``None``).
        headers:     Response headers (e.g. for ``Retry-After``/rate-limit info).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        response: Any = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        self.response = response
        self.headers = dict(headers or {})

    def __str__(self) -> str:
        bits = [f"[{self.status_code}]"]
        if self.code:
            bits.append(f"{self.code}:")
        bits.append(self.message)
        if self.request_id:
            bits.append(f"(request_id={self.request_id})")
        return " ".join(bits)


class BadRequestError(APIError):
    """400 — the request was malformed or missing required fields."""


class AuthenticationError(APIError):
    """401 — the API key is missing, malformed, or revoked."""


class PermissionDeniedError(APIError):
    """403 — authenticated, but not allowed (wrong scope, denied open, etc.)."""


class NotFoundError(APIError):
    """404 — the addressed resource does not exist."""


class RateLimitError(APIError):
    """429 — per-minute or monthly quota exceeded.

    ``retry_after`` is the number of seconds the server asked you to wait
    (from the ``Retry-After`` header), when present.
    """

    def __init__(self, *args: Any, retry_after: Optional[float] = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class GateNotOpenedError(APIError):
    """504 — the gate did not confirm the open within the backend's window."""


class UpstreamError(APIError):
    """502/503 — the backend (kindlyWAMP) was unavailable or failed."""


class ServerError(APIError):
    """Any other 5xx response."""


# Maps the most specific exception class for a given HTTP status / error code.
def exception_for(status_code: int, code: Optional[str]) -> type[APIError]:
    if code == "did_not_open" or status_code == 504:
        return GateNotOpenedError
    if status_code == 400:
        return BadRequestError
    if status_code == 401:
        return AuthenticationError
    if status_code == 403:
        return PermissionDeniedError
    if status_code == 404:
        return NotFoundError
    if status_code == 429:
        return RateLimitError
    if status_code in (502, 503):
        return UpstreamError
    if status_code >= 500:
        return ServerError
    return APIError
