from pathlib import Path

from datamind.profiler import format_profile_summary, profile_dataset

SAMPLE_PATH = Path(__file__).parent.parent / "sample_data" / "sample_sales.csv"


def test_profile_dataset_shape():
    profile = profile_dataset(SAMPLE_PATH)
    assert profile["row_count"] == 15
    assert profile["column_count"] == 11
    assert profile["duplicate_row_count"] == 0


def test_profile_dataset_numeric_column_stats():
    profile = profile_dataset(SAMPLE_PATH)
    revenue = profile["columns"]["revenue"]
    assert "stats" in revenue
    assert revenue["stats"]["min"] == 40.0
    assert revenue["missing_count"] == 0


def test_profile_dataset_categorical_column_top_values():
    profile = profile_dataset(SAMPLE_PATH)
    region = profile["columns"]["region"]
    assert "top_values" in region
    assert sum(region["top_values"].values()) == 15


def test_profile_dataset_missing_file_raises():
    try:
        profile_dataset("does-not-exist.csv")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_format_profile_summary_contains_key_facts():
    profile = profile_dataset(SAMPLE_PATH)
    summary = format_profile_summary(profile)
    assert "Rows: 15" in summary
    assert "revenue" in summary
