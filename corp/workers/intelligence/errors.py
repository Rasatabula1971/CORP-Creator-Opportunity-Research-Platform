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
