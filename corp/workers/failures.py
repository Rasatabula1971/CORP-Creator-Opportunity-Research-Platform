"""What a pipeline is allowed to persist about a failure.

A ResearchRun's ``error_message``, a ResearchQuery's ``error``, a
candidate's ``naming_error`` and a source-health ``last_error`` are all
read back through the API and shown on the dashboard. An exception's own
text is not safe there: an asyncpg error carries the DSN (with password),
an httpx error the full request URL (with the API key as a query
parameter), an adapter error a filesystem path. The full exception goes
to the server log, where it belongs; the row gets :func:`describe_failure`.

Two kinds of message are kept verbatim because our own code wrote them:
a :class:`PipelineFailureError` (a summary a pipeline composed for the reader)
and anything exposing a ``safe_message`` attribute (see LLMCallError).
"""

from __future__ import annotations

MAX_STORED_ERROR = 500
_SUFFIX = "; details in the server log"


class PipelineFailureError(RuntimeError):
    """A failure whose message a pipeline composed itself, from data it
    controls, so it is safe to persist verbatim."""

    @property
    def safe_message(self) -> str:
        return str(self)


def describe_failure(exc: BaseException, *, limit: int = MAX_STORED_ERROR) -> str:
    """The text a run row (or any API-visible field) records for ``exc``.

    Never the exception's own message unless it declares one safe: for
    everything else the exception type is all a reader gets here, with
    the traceback in the server log.
    """
    safe = getattr(exc, "safe_message", None)
    if isinstance(safe, str) and safe:
        return safe[:limit]
    return f"{type(exc).__name__}{_SUFFIX}"[:limit]
