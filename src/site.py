"""Repo-wide settings that are not about any one campaign.

Today that is one thing: the public address rendered videos are served from.
"""

from __future__ import annotations

import re
from pathlib import Path
import yaml

from src.errors import ConfigError

SITE_FILE = "site.yaml"

_RELEASE_DOWNLOAD = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/releases/download/(?P<tag>[^/]+)/(?P<name>[^/?#]+)$"
)


def media_base(repo_root: Path) -> str:
    """The public base URL for rendered videos, or "" to use GitHub's own."""
    path = repo_root / SITE_FILE
    if not path.is_file():
        return ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{SITE_FILE} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{SITE_FILE} must be a mapping of settings")
    base = str(data.get("media_base_url") or "").strip().rstrip("/")
    if base and not base.startswith("https://"):
        raise ConfigError(f"{SITE_FILE}: media_base_url must start with https://")
    return base


def public_media_url(url: str, base: str) -> str:
    """Rewrite a GitHub Release download link onto the public media address.

    Anything that is not a Release link — including one already rewritten —
    is returned untouched, so this is safe to apply more than once and to
    queue items rendered before the address was configured.
    """
    if not base:
        return url
    match = _RELEASE_DOWNLOAD.match(url)
    if not match:
        return url
    return f"{base}/{match['tag']}/{match['name']}"
