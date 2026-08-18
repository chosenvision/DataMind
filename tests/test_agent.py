from types import SimpleNamespace

import pytest

from datamind.agent import DashboardPlanError, _check_finish_reason, _extract_json


def test_extract_json_parses_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_raises_friendly_error_on_truncated_json():
    truncated = '{"a": 1, "b": "this string never closes'
    with pytest.raises(DashboardPlanError) as exc_info:
        _extract_json(truncated)
    message = str(exc_info.value)
    assert "cut off" in message
    assert "Analysis Depth" in message


def test_check_finish_reason_ok_when_no_candidates():
    _check_finish_reason(SimpleNamespace(candidates=[]))
    _check_finish_reason(SimpleNamespace())


def test_check_finish_reason_ok_on_stop():
    response = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])
    _check_finish_reason(response)  # should not raise


def test_check_finish_reason_raises_actionable_error_on_max_tokens():
    response = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="MAX_TOKENS"))])
    with pytest.raises(DashboardPlanError) as exc_info:
        _check_finish_reason(response)
    message = str(exc_info.value)
    assert "cut off" in message
    assert "Analysis Depth" in message


def test_check_finish_reason_raises_on_other_stop_reasons():
    response = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="SAFETY"))])
    with pytest.raises(DashboardPlanError, match="SAFETY"):
        _check_finish_reason(response)
