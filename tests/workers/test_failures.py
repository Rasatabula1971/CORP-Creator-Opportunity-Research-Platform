"""What a pipeline may persist about a failure (corp.workers.failures)."""

from corp.workers.failures import MAX_STORED_ERROR, PipelineFailureError, describe_failure
from corp.workers.intelligence.errors import LLMCallError


def test_a_foreign_exception_is_reduced_to_its_type():
    exc = ConnectionError(
        "connect to postgresql://corp:hunter2@db.internal:5432/corp failed "
        "(see /home/corp/.env)"
    )
    text = describe_failure(exc)
    assert text == "ConnectionError; details in the server log"
    assert "hunter2" not in text and "/home/" not in text


def test_a_pipeline_failure_keeps_its_own_summary():
    exc = PipelineFailureError("no niche source was available: reddit=disconnected")
    assert describe_failure(exc) == "no niche source was available: reddit=disconnected"


def test_llm_call_error_keeps_the_stage_but_not_the_cause_text():
    cause = RuntimeError("HTTP 401 for https://api.example/v1?key=sk-secret")
    text = describe_failure(LLMCallError("extraction", cause))
    assert text == "extraction: RuntimeError; details in the server log"
    assert "sk-secret" not in text


def test_stored_text_is_bounded():
    exc = PipelineFailureError("x" * (MAX_STORED_ERROR * 3))
    assert len(describe_failure(exc)) == MAX_STORED_ERROR
    assert len(describe_failure(exc, limit=40)) == 40
