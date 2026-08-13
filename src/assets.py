"""Media hosting on GitHub Releases (SPEC §5).

Responsibility: fetch a campaign's source assets, publish rendered MP4s at a
public URL Buffer can fetch, and delete Releases past their retention window.

Why GitHub Releases: Buffer's media upload is URL-only (verified — see README
§0, ``VideoAssetInput.url`` is a non-null String), so the rendered file must be
reachable unauthenticated at publish time. A public repo's Release assets are,
which avoids standing up Cloudflare R2 — no extra account, no card, no domain.

The URL must stay live until Buffer actually publishes, which is why the cleanup
window (14 days) is comfortably longer than the deepest possible queue.

This module and ``publishers/`` are the only places in ``src/`` that make HTTP
calls (SPEC §2.2).
"""

from __future__ import annotations

import mimetypes
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import requests

from src.errors import AuthError, MediaStoreError
from src.logging import StructuredLogger
from src.ports import Clock

GITHUB_API = "https://api.github.com"
GITHUB_UPLOADS = "https://uploads.github.com"

#: GitHub's per-file cap on Release assets (SPEC §3).
MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024

REQUEST_TIMEOUT_SEC = 60
UPLOAD_TIMEOUT_SEC = 600


@dataclass(frozen=True)
class RemoteAsset:
    """One file published to the media store."""

    name: str
    url: str
    size_bytes: int


class MediaStore(ABC):
    """Somewhere to put rendered videos and get back a public URL.

    The seam that lets GitHub Releases be swapped for R2/S3 without touching
    render, queue or publish (SPEC §2.2).
    """

    @abstractmethod
    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        """Fetch every asset from a named collection into ``dest_dir``."""

    @abstractmethod
    def list_assets(self, tag: str) -> list[str]:
        """Names already in a collection, without downloading them.

        Ingest needs this to continue a numbering sequence rather than
        clobbering an existing ``hook_03.mp4``; downloading a whole library to
        answer that would be absurd.
        """

    @abstractmethod
    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        """Upload files and return their public URLs."""

    @abstractmethod
    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        """Delete collections older than the retention window. Returns names."""


class GitHubReleasesStore(MediaStore):
    """MediaStore backed by GitHub Releases on a public repo."""

    def __init__(
        self,
        repo: str,
        token: str,
        log: StructuredLogger,
        clock: Clock,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if "/" not in repo:
            raise MediaStoreError(f"repo must be 'owner/name', got {repo!r}")
        self._repo = repo
        self._token = token
        self._log = log
        self._clock = clock
        self._session = session or requests.Session()
        # Injected so tests exercise the retry path without actually waiting;
        # backoff delay is behaviour, not something to skip in tests.
        self._sleep = sleep

    # ------------------------------------------------------------------ http

    def _headers(self, **extra: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            # Pinning the API version stops a future GitHub default from
            # silently changing response shapes under a long-running cron.
            "X-GitHub-Api-Version": "2022-11-28",
            **extra,
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: int = REQUEST_TIMEOUT_SEC,
        attempts: int = 3,
        **kwargs: Any,
    ) -> requests.Response:
        """Issue a request, retrying only what is worth retrying (SPEC §12)."""
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._session.request(
                    method, url, headers=self._headers(**kwargs.pop("headers", {})),
                    timeout=timeout, **kwargs
                )
            except requests.RequestException as exc:
                last = exc
                self._log.warning(
                    "github_request_error", url=url, attempt=attempt, error=str(exc)
                )
                if attempt == attempts:
                    raise MediaStoreError(f"{method} {url} failed: {exc}") from exc
                self._sleep(2 ** attempt)
                continue

            if response.status_code in (401, 403):
                # 403 is also GitHub's rate-limit status; distinguish by header
                # rather than by message text (SPEC §2.2).
                if response.headers.get("X-RateLimit-Remaining") == "0":
                    reset = response.headers.get("X-RateLimit-Reset", "?")
                    raise MediaStoreError(
                        f"GitHub rate limit exhausted, resets at {reset}"
                    )
                raise AuthError(
                    f"GitHub rejected credentials for {method} {url} "
                    f"({response.status_code}) — check GITHUB_TOKEN scope"
                )
            if response.status_code >= 500:
                last = MediaStoreError(f"GitHub {response.status_code} on {url}")
                if attempt == attempts:
                    raise last
                self._sleep(2 ** attempt)
                continue
            return response

        raise MediaStoreError(f"{method} {url} exhausted retries: {last}")

    # -------------------------------------------------------------- releases

    def _get_release(self, tag: str) -> dict[str, Any] | None:
        response = self._request(
            "GET", f"{GITHUB_API}/repos/{self._repo}/releases/tags/{tag}"
        )
        if response.status_code == 404:
            return None
        if not response.ok:
            raise MediaStoreError(
                f"could not read release {tag}: {response.status_code} {response.text[:300]}"
            )
        data: dict[str, Any] = response.json()
        return data

    def _ensure_release(self, tag: str) -> dict[str, Any]:
        existing = self._get_release(tag)
        if existing is not None:
            return existing
        response = self._request(
            "POST",
            f"{GITHUB_API}/repos/{self._repo}/releases",
            json={
                "tag_name": tag,
                "name": tag,
                "body": f"Rendered videos for {tag}. Managed by ugc-factory; "
                        f"deleted automatically by the cleanup job.",
                # Not a draft: draft releases have no public asset URLs, so
                # Buffer could not fetch the video.
                "draft": False,
                "prerelease": True,
            },
        )
        if not response.ok:
            raise MediaStoreError(
                f"could not create release {tag}: "
                f"{response.status_code} {response.text[:300]}"
            )
        created: dict[str, Any] = response.json()
        self._log.info("release_created", tag=tag, id=created.get("id"))
        return created

    # -------------------------------------------------------------- download

    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        release = self._get_release(tag)
        if release is None:
            raise MediaStoreError(
                f"assets release {tag!r} not found in {self._repo} — "
                f"create it and upload hooks/, bodies/ and music/ first"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)

        downloaded: list[Path] = []
        for asset in release.get("assets") or []:
            name = str(asset["name"])
            dest = dest_dir / name
            # Assets are immutable once uploaded, so a size match is a safe
            # cache hit and saves re-downloading a library every render.
            if dest.is_file() and dest.stat().st_size == int(asset["size"]):
                downloaded.append(dest)
                continue
            self._download_one(int(asset["id"]), dest)
            downloaded.append(dest)

        self._log.info("assets_downloaded", tag=tag, count=len(downloaded))
        return downloaded

    def list_assets(self, tag: str) -> list[str]:
        release = self._get_release(tag)
        if release is None:
            return []
        return [str(a["name"]) for a in (release.get("assets") or [])]

    def _download_one(self, asset_id: int, dest: Path) -> None:
        response = self._request(
            "GET",
            f"{GITHUB_API}/repos/{self._repo}/releases/assets/{asset_id}",
            headers={"Accept": "application/octet-stream"},
            stream=True,
            timeout=UPLOAD_TIMEOUT_SEC,
        )
        if not response.ok:
            raise MediaStoreError(
                f"download of asset {asset_id} failed: {response.status_code}"
            )
        # Write to a temp path and rename, so an interrupted download cannot
        # leave a truncated file that the size-based cache check then accepts.
        temp = dest.with_suffix(dest.suffix + ".part")
        with temp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
        temp.replace(dest)

    # ---------------------------------------------------------------- upload

    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        release = self._ensure_release(tag)
        upload_url = str(release["upload_url"]).split("{", 1)[0]
        existing = {str(a["name"]): a for a in (release.get("assets") or [])}

        published: list[RemoteAsset] = []
        for path in files:
            if not path.is_file():
                raise MediaStoreError(f"cannot publish missing file: {path}")
            size = path.stat().st_size
            if size == 0:
                raise MediaStoreError(f"refusing to publish empty file: {path}")
            if size > MAX_ASSET_BYTES:
                raise MediaStoreError(
                    f"{path.name} is {size} bytes, over GitHub's 2 GB asset cap"
                )

            if path.name in existing:
                # Re-uploading the same name silently 422s; deleting first makes
                # a re-run of a partially failed render idempotent.
                self._delete_asset(int(existing[path.name]["id"]))

            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            with path.open("rb") as handle:
                response = self._request(
                    "POST",
                    f"{upload_url}?name={path.name}",
                    headers={"Content-Type": content_type},
                    data=handle,
                    timeout=UPLOAD_TIMEOUT_SEC,
                )
            if not response.ok:
                raise MediaStoreError(
                    f"upload of {path.name} failed: "
                    f"{response.status_code} {response.text[:300]}"
                )
            asset = response.json()
            published.append(
                RemoteAsset(
                    name=path.name,
                    url=str(asset["browser_download_url"]),
                    size_bytes=size,
                )
            )
            self._log.info("asset_uploaded", tag=tag, name=path.name, size_bytes=size)

        return published

    def _delete_asset(self, asset_id: int) -> None:
        self._request(
            "DELETE", f"{GITHUB_API}/repos/{self._repo}/releases/assets/{asset_id}"
        )

    # --------------------------------------------------------------- cleanup

    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        """Delete Releases whose tag starts with ``prefix`` and are past retention.

        The window must stay comfortably longer than the deepest queue: deleting
        a Release whose video Buffer has not published yet breaks that post.
        """
        cutoff = self._clock.now() - timedelta(days=older_than_days)
        deleted: list[str] = []
        for release in self._iter_releases():
            tag = str(release.get("tag_name") or "")
            if not tag.startswith(prefix):
                continue
            created_raw = str(release.get("created_at") or "")
            try:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError:
                self._log.warning("release_unparseable_date", tag=tag, raw=created_raw)
                continue
            if created >= cutoff:
                continue

            response = self._request(
                "DELETE",
                f"{GITHUB_API}/repos/{self._repo}/releases/{release['id']}",
            )
            if not response.ok:
                self._log.warning(
                    "release_delete_failed", tag=tag, status=response.status_code
                )
                continue
            deleted.append(tag)
            self._log.info("release_deleted", tag=tag, created_at=created_raw)
        return deleted

    def _iter_releases(self) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            response = self._request(
                "GET",
                f"{GITHUB_API}/repos/{self._repo}/releases",
                params={"per_page": 100, "page": page},
            )
            if not response.ok:
                raise MediaStoreError(
                    f"could not list releases: {response.status_code}"
                )
            batch: list[dict[str, Any]] = response.json()
            if not batch:
                return
            yield from batch
            if len(batch) < 100:
                return
            page += 1


@dataclass(frozen=True)
class LocalLibrary:
    """Source clips on disk, grouped by the folder they came from.

    SPEC §7: hooks/, bodies/ and music/ are populated by dropping files in — no
    registration step, no config edit. Grouping is therefore by filename prefix,
    since GitHub Release assets are a flat namespace with no directories.
    """

    hooks: tuple[Path, ...]
    bodies: tuple[Path, ...]
    music: tuple[Path, ...]

    VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm")
    AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav")

    @classmethod
    def from_directory(cls, root: Path) -> "LocalLibrary":
        """Group a flat directory of downloaded assets by ``<kind>_`` prefix."""
        def pick(prefix: str, suffixes: tuple[str, ...]) -> tuple[Path, ...]:
            return tuple(
                sorted(
                    p for p in root.iterdir()
                    if p.is_file()
                    and p.name.lower().startswith(prefix)
                    and p.suffix.lower() in suffixes
                )
            )

        return cls(
            hooks=pick("hook", cls.VIDEO_SUFFIXES),
            bodies=pick("body", cls.VIDEO_SUFFIXES),
            music=pick("music", cls.AUDIO_SUFFIXES),
        )

    def by_name(self) -> dict[str, Path]:
        """Filename -> path, for resolving a Selection back to real files."""
        return {p.name: p for p in (*self.hooks, *self.bodies, *self.music)}


def check_music_licenses(
    music: tuple[Path, ...], licenses_file: Path, log: StructuredLogger
) -> list[str]:
    """Return music filenames with no entry in LICENSES.md (SPEC §4.4, §7).

    A warning rather than a hard failure: a missing licence line is a
    bookkeeping problem, and blocking the whole night's render over one would be
    worse than posting. The names are returned so the digest can carry them.
    """
    if not music:
        return []
    if not licenses_file.is_file():
        names = [p.name for p in music]
        log.warning("music_licenses_file_missing", path=str(licenses_file), tracks=names)
        return names

    text = licenses_file.read_text(encoding="utf-8", errors="replace")
    missing = [p.name for p in music if p.name not in text]
    if missing:
        log.warning("music_licenses_missing", tracks=missing, path=str(licenses_file))
    return missing


def github_token_from_env(env: dict[str, str] | None = None) -> str:
    """Read the token Actions injects, failing loud if it is absent."""
    source = env if env is not None else dict(os.environ)
    token = source.get("GITHUB_TOKEN") or source.get("GH_TOKEN") or ""
    if not token:
        raise AuthError(
            "GITHUB_TOKEN is not set — the media store cannot read or write "
            "Releases without it"
        )
    return token
