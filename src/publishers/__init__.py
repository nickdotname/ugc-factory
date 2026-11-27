"""The publishers, and the one place that knows which account gets which.

``accounts.yaml`` says ``provider:``; everything above the seam holds a
``Publisher`` and never asks. Imports are inside the function so that
importing ``src.publishers.base`` does not drag every backend in.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from src.accounts import AccountConfig, Provider
from src.config import YOUTUBE_CLIENT_ID_SECRET, YOUTUBE_CLIENT_SECRET_SECRET
from src.errors import ConfigError

if TYPE_CHECKING:  # pragma: no cover
    from src.logging import StructuredLogger
    from src.publishers.base import Publisher

#: Providers whose held posts live in the repo (``outbox/``) rather than on
#: the backend's servers: their files must be committed with the queue, and
#: ``publish-due`` sends what is theirs.
DIRECT_PROVIDERS: frozenset[Provider] = frozenset({Provider.INSTAGRAM, Provider.YOUTUBE})

#: Env override for the per-project daily YouTube upload cap.
YOUTUBE_DAILY_UPLOADS_VAR = "YT_DAILY_UPLOADS"


def real_publisher(
    account: AccountConfig,
    secret: str,
    log: "StructuredLogger",
    *,
    env: Mapping[str, str] | None = None,
    outbox_dir: Path,
) -> "Publisher":
    """The publisher one account posts through. Never a dry-run stand-in.

    ``secret`` is the value of the account's ``api_key_secret`` slot: a Buffer
    key, an Instagram token, or a YouTube refresh token. YouTube also needs the
    project's client id and secret, read from ``env`` by their fixed names.
    """
    env = os.environ if env is None else env
    if account.provider is Provider.INSTAGRAM:
        from src.publishers.instagram import InstagramPublisher

        return InstagramPublisher(
            secret, log, outbox_dir=outbox_dir, login=account.login.value,
        )
    if account.provider is Provider.YOUTUBE:
        from src.publishers.youtube import DEFAULT_DAILY_UPLOADS, YouTubePublisher

        client_id = env.get(YOUTUBE_CLIENT_ID_SECRET) or ""
        client_secret = env.get(YOUTUBE_CLIENT_SECRET_SECRET) or ""
        if not client_id or not client_secret:
            raise ConfigError(
                f"{YOUTUBE_CLIENT_ID_SECRET} / {YOUTUBE_CLIENT_SECRET_SECRET} are not "
                f"set — cannot publish to {account.name}"
            )
        cap = env.get(YOUTUBE_DAILY_UPLOADS_VAR) or ""
        return YouTubePublisher(
            secret, log,
            client_id=client_id, client_secret=client_secret,
            outbox_dir=outbox_dir,
            token_secret=account.api_key_secret,
            daily_uploads=int(cap) if cap.isdigit() else DEFAULT_DAILY_UPLOADS,
        )
    from src.publishers.buffer import BufferPublisher

    return BufferPublisher(secret, log, organization_id=account.organization_id)


def holds_posts_in_repo(publisher: object) -> bool:
    """Whether this publisher wrote outbox files the caller must commit."""
    return bool(getattr(publisher, "touched", None))
