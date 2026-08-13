"""Exception hierarchy for the UGC factory.

Responsibility: define every error the pipeline can raise, and encode
*retryability as a property of the class* rather than of a message string.

SPEC §2.2: "Never branch on error message strings — Buffer will change its
wording and the retry logic will silently invert." Callers ask
``err.retryable``; they never read ``str(err)`` to make a decision.
"""

from __future__ import annotations


class UgcError(Exception):
    """Base for every error this system raises deliberately.

    A bare ``Exception`` escaping to the top level means we failed to classify
    something, and the CLI treats that as a crash rather than a handled failure.
    """

    #: Whether retrying the identical operation could plausibly succeed.
    retryable: bool = False


class ConfigError(UgcError):
    """Campaign config is missing, malformed, or violates the schema.

    Never retryable: the file will not fix itself between attempts.
    """

    retryable = False


class ValidationError(UgcError):
    """A produced artifact failed a hard precondition before leaving the box.

    Raised by the renderer's output checks (SPEC §6) and by queue-item checks
    before a push. Not retryable — the same inputs produce the same bad output.
    """

    retryable = False


class RenderError(UgcError):
    """ffmpeg/ffprobe failed, or a source clip is unusable.

    Not retryable by default: a malformed source clip stays malformed. Transient
    render failures (disk full, OOM) are rare enough that blind retry costs more
    than it saves.
    """

    retryable = False


class SelectionError(UgcError):
    """The selector cannot produce a valid combination even after relaxation.

    Means the asset library is too small for the configured cadence (SPEC §10).
    """

    retryable = False


class MediaStoreError(UgcError):
    """Upload/download against the media store failed."""

    retryable = True


class PublishError(UgcError):
    """The publisher could not place the post.

    Base for publish failures; subclasses below carve out the cases where
    retryability differs from this default.
    """

    retryable = True


class AuthError(PublishError):
    """Credentials are missing, expired, or lack scope for the action.

    SPEC §12: "Do not retry auth failures — alert and stop." Retrying an auth
    failure 3× just burns quota and delays the alert.
    """

    retryable = False


class QuotaError(PublishError):
    """A hard limit was hit — channel queue full, or plan/posting limit reached.

    Not retryable *within a run*: the limit is still there a second later. The
    next scheduled run is the retry, by which time a slot may have freed.
    """

    retryable = False


class InvalidPostError(PublishError):
    """The remote API rejected the post payload as invalid.

    Not retryable: identical input yields identical rejection. This is the
    error class that must never be swallowed — it means we built a bad payload.
    """

    retryable = False


class RateLimitError(PublishError):
    """The remote API asked us to slow down.

    Retryable with backoff — this is the canonical retryable publish failure.
    """

    retryable = True


class NotifyError(UgcError):
    """The alerting webhook itself failed.

    Retryable, but a failure here must never mask the original error that we
    were trying to report.
    """

    retryable = True
