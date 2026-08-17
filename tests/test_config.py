import pytest

from datamind.config import UserConfig


def test_default_config_is_valid():
    config = UserConfig()
    assert config.preferred_tool == "Python"
    assert config.analysis_depth == "Standard Analysis"


def test_invalid_tool_raises():
    with pytest.raises(ValueError):
        UserConfig(preferred_tool="Excel Online")


def test_invalid_analysis_depth_raises():
    with pytest.raises(ValueError):
        UserConfig(analysis_depth="Ultra Deep Dive")


def test_to_brief_includes_optional_fields_when_set():
    config = UserConfig(
        preferred_tool="Power BI",
        dashboard_objective="Sales Analysis",
        target_audience="CEO",
        business_context="Q1 retail performance review",
    )
    brief = config.to_brief()
    assert "Power BI" in brief
    assert "Sales Analysis" in brief
    assert "CEO" in brief
    assert "Q1 retail performance review" in brief


def test_to_brief_flags_unspecified_optional_fields():
    brief = UserConfig().to_brief()
    assert "Not specified" in brief
