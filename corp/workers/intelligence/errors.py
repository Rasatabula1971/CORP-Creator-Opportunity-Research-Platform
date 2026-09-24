"""Typed failures raised by the LLM helper functions.

The helpers used to swallow provider errors and return empty results, which
made a dead provider look like an empty audience. They now raise
:class:`LLMCallError` so pipelines can count failures and mark runs partial.
"""


class LLMCallError(RuntimeError):
    """A single LLM call failed (transport, provider, or unparseable output)."""

    def __init__(self, stage: str, cause: BaseException) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"{stage}: {cause}")

    @property
    def safe_message(self) -> str:
        """What a run row may record (see corp.workers.failures): the stage
        and the cause's type, never the cause's text -- a provider error
        can carry the request URL with the API key in it."""
        return f"{self.stage}: {type(self.cause).__name__}; details in the server log"
