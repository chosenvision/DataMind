from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from datamind.dashboard import (
    build_workbook,
    compute_kpi_summary,
    compute_kpi_value,
    format_kpi_value,
    load_dataframe,
)

SAMPLE_PATH = Path(__file__).parent.parent / "sample_data" / "sample_sales.csv"


@pytest.fixture
def df():
    return load_dataframe(SAMPLE_PATH)


@pytest.fixture
def plan():
    return {
        "dataset_classification": "Sales",
        "executive_summary": "Revenue grew steadily, led by the North region.",
        "kpis": [
            {"name": "Total Revenue", "column": "revenue", "agg": "sum", "format": "currency"},
            {"name": "Total Orders", "agg": "row_count", "format": "number"},
            {"name": "Avg Discount", "column": "discount", "agg": "mean", "format": "percent"},
            {"name": "Bogus", "column": "does_not_exist", "agg": "sum", "format": "number"},
        ],
        "charts": [
            {"title": "Revenue by Region", "type": "bar", "category_column": "region", "value_column": "revenue", "agg": "sum"},
            {"title": "Revenue Trend", "type": "line", "date_column": "order_date", "value_column": "revenue", "agg": "sum", "freq": "M"},
            {"title": "Bogus chart", "type": "bar", "category_column": "nope", "value_column": "revenue", "agg": "sum"},
        ],
        "insights_text": ["North region drives the largest share of revenue."],
        "risks": ["Revenue is concentrated in a few customers."],
        "opportunities": ["Home category has room to grow."],
        "recommendations": [{"action": "Promote Home category", "priority": "Medium", "impact": "Lift revenue"}],
        "assumptions": ["Discount is stored as a fraction."],
        "limitations": ["No marketing spend data."],
    }


def test_compute_kpi_value_sum(df):
    kpi = {"column": "revenue", "agg": "sum"}
    assert compute_kpi_value(df, kpi) == pytest.approx(1413.25)


def test_compute_kpi_value_row_count(df):
    assert compute_kpi_value(df, {"agg": "row_count"}) == 15


def test_format_kpi_value_currency_small():
    assert format_kpi_value(94.223, "currency") == "$94.22"


def test_format_kpi_value_currency_large():
    assert format_kpi_value(1413.25, "currency") == "$1,413"


def test_format_kpi_value_percent_multiplies_by_100():
    assert format_kpi_value(0.033, "percent") == "3.3%"


def test_format_kpi_value_number_integer():
    assert format_kpi_value(15, "number") == "15"


def test_compute_kpi_summary_drops_invalid_columns(df, plan):
    summary = compute_kpi_summary(df, plan)
    names = [k["name"] for k in summary]
    assert "Bogus" not in names
    assert len(summary) == 3
    total_revenue = next(k for k in summary if k["name"] == "Total Revenue")
    assert total_revenue["value"] == "$1,413"
    total_orders = next(k for k in summary if k["name"] == "Total Orders")
    assert total_orders["value"] == "15"


def test_build_workbook_has_expected_sheets(df, plan):
    wb = build_workbook(df, plan)
    assert wb.sheetnames == [
        "Overview",
        "Dashboard",
        "Data",
        "Power BI Guide",
        "Assumptions & Limitations",
    ]


def test_build_workbook_is_valid_and_reloadable(df, plan):
    wb = build_workbook(df, plan)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    reloaded = openpyxl.load_workbook(buffer)
    assert reloaded.sheetnames == wb.sheetnames


def test_build_workbook_data_sheet_matches_dataframe_shape(df, plan):
    wb = build_workbook(df, plan)
    ws = wb["Data"]
    assert ws.max_row == len(df) + 1
    assert ws.max_column == len(df.columns)


def test_build_workbook_dashboard_sheet_only_has_valid_charts(df, plan):
    wb = build_workbook(df, plan)
    # 3 chart specs in the plan, one references a nonexistent column and is dropped
    assert len(wb["Dashboard"]._charts) == 2


def test_build_workbook_power_bi_sheet_has_dax_for_each_kpi(df, plan):
    wb = build_workbook(df, plan)
    ws = wb["Power BI Guide"]
    text = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "SUM(Data[revenue])" in text
    assert "COUNTROWS(Data)" in text


def test_build_workbook_omits_dashboard_sheet_when_no_charts(df, plan):
    plan = {**plan, "charts": []}
    wb = build_workbook(df, plan)
    assert "Dashboard" not in wb.sheetnames
