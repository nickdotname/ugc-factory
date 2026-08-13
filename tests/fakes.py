"""Test doubles for the two network boundaries.

SPEC §2.2: "Tests that don't hit the network. Buffer's real responses — success,
each error mode, rate limit, reminder-mode fallback — are captured once as
fixtures and replayed."

``FakeSession`` matches ``requests.Session.request``'s signature closely enough
that the production code under test cannot tell the difference, and records
every call so tests can assert on what was actually sent.
"""

from __future__ import annotations

import json as jsonlib
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class RecordedRequest:
    method: str
    url: str
    kwargs: dict[str, Any]

    @property
    def json_body(self) -> Any:
        return self.kwargs.get("json")


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(
        self,
        status_code: int = 200,
        json_body: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = text or (jsonlib.dumps(json_body) if json_body is not None else "")
        self.headers = headers or {}
        self._content = content

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


Handler = Callable[[RecordedRequest], FakeResponse]


class FakeSession:
    """Routes requests to handlers by (method, url-substring)."""

    def __init__(self) -> None:
        self.calls: list[RecordedRequest] = []
        self._routes: list[tuple[str, str, Handler]] = []
        self.default: FakeResponse | None = None

    def route(self, method: str, url_contains: str, handler: Handler | FakeResponse):
        """Register a handler. Later registrations take precedence."""
        h: Handler = handler if callable(handler) else (lambda _r, resp=handler: resp)
        self._routes.insert(0, (method.upper(), url_contains, h))
        return self

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        call = RecordedRequest(method.upper(), url, kwargs)
        self.calls.append(call)
        for m, fragment, handler in self._routes:
            if m == call.method and fragment in url:
                return handler(call)
        if self.default is not None:
            return self.default
        raise AssertionError(f"unrouted request in test: {method} {url}")

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """requests.Session.post — notify uses this rather than .request."""
        return self.request("POST", url, **kwargs)

    def calls_to(self, fragment: str) -> list[RecordedRequest]:
        return [c for c in self.calls if fragment in c.url]
