from pathlib import Path

import pandas as pd
import pytest

from datamind.profiler import format_profile_summary, load_dataframe, profile_dataset

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


def test_load_dataframe_coerces_dollar_formatted_columns_to_numeric(tmp_path):
    csv_path = tmp_path / "financial_sample.csv"
    csv_path.write_text(
        "Segment,Sales,Profit\n"
        "Government,\"$ 1,618.50 \",\"$ (42.00)\"\n"
        "Midmarket,\"$ 2,000.00 \",\"$ 300.00\"\n"
        "Government,\"$ 500.25 \",\"$ (10.75)\"\n"
    )

    df = load_dataframe(csv_path)

    assert pd.api.types.is_numeric_dtype(df["Sales"])
    assert pd.api.types.is_numeric_dtype(df["Profit"])
    assert df["Sales"].sum() == pytest.approx(4118.75)
    assert df["Profit"].tolist() == pytest.approx([-42.0, 300.0, -10.75])
    # a genuine text column with no currency formatting is left untouched
    assert not pd.api.types.is_numeric_dtype(df["Segment"])


def test_load_dataframe_leaves_non_numeric_text_columns_alone():
    df = load_dataframe(SAMPLE_PATH)
    assert not pd.api.types.is_numeric_dtype(df["region"])
