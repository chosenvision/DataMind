"""Builds a real, downloadable Excel dashboard from a dataset and an analysis plan.

The analysis plan (see agent.DataAnalystAgent.plan_dashboard) tells this module
*which* KPIs and charts matter and how to compute them (column + aggregation),
but every number that ends up in the workbook is computed here with pandas
against the actual data - never taken verbatim from the model - so the
dashboard cannot show a hallucinated figure.
"""

from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from datamind.profiler import load_dataframe as _load_dataframe

PALETTE = ["4338CA", "0D9488", "D97706", "7C3AED", "DC2626", "2563EB"]

_AGG_FUNCS = {
    "sum": "sum",
    "mean": "mean",
    "average": "mean",
    "median": "median",
    "max": "max",
    "min": "min",
    "count": "count",
    "nunique": "nunique",
}

_HEADER_FILL = PatternFill("solid", fgColor="12131C")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
_TITLE_FONT = Font(bold=True, size=16, color="12131C")
_SUBTITLE_FONT = Font(size=11, color="5A5D72")
_KPI_LABEL_FONT = Font(size=10, bold=True, color="5A5D72")
_KPI_VALUE_FONT = Font(size=20, bold=True, color="12131C")
_SECTION_FONT = Font(size=13, bold=True, color="12131C")
_THIN_BORDER = Border(*(Side(style="thin", color="E5E5EA") for _ in range(4)))


def load_dataframe(path: str | Path) -> pd.DataFrame:
    """Load a dataset the same way datamind.profiler does, for reuse by the dashboard builder."""
    return _load_dataframe(path)


def _valid_kpis(df: pd.DataFrame, kpis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for kpi in kpis:
        agg_raw = str(kpi.get("agg", "")).lower()
        if agg_raw == "row_count":
            valid.append({**kpi, "agg": "row_count", "column": None})
            continue
        agg = _AGG_FUNCS.get(agg_raw)
        column = kpi.get("column")
        if agg is None or not column or column not in df.columns:
            continue
        valid.append({**kpi, "agg": agg})
    return valid[:8]


def compute_kpi_value(df: pd.DataFrame, kpi: dict[str, Any]) -> float | int:
    if kpi["agg"] == "row_count":
        return len(df)
    series = df[kpi["column"]]
    if kpi["agg"] in {"sum", "mean", "median", "max", "min"}:
        series = pd.to_numeric(series, errors="coerce")
    value = getattr(series, kpi["agg"])()
    return 0 if pd.isna(value) else value


def format_kpi_value(value: float | int, fmt: str | None) -> str:
    fmt = (fmt or "number").lower()
    if fmt == "currency":
        return f"${value:,.2f}" if abs(value) < 1000 else f"${value:,.0f}"
    if fmt == "percent":
        # KPI values feeding "percent" are fractions (e.g. a 0.1 discount rate),
        # matching how spreadsheet percent formatting works.
        return f"{value * 100:,.1f}%"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    return f"{int(value):,}"


def compute_kpi_summary(df: pd.DataFrame, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the plan's KPI specs against real columns and compute+format each value.

    Shared by the Excel builder and the API's on-page summary so both surfaces show
    the exact same pandas-computed numbers.
    """
    kpis = _valid_kpis(df, plan.get("kpis", []))
    summary = []
    for kpi in kpis:
        value = compute_kpi_value(df, kpi)
        summary.append(
            {
                "name": kpi.get("name", "KPI"),
                "value": format_kpi_value(value, kpi.get("format")),
                "meaning": kpi.get("meaning", ""),
            }
        )
    return summary


def _valid_charts(df: pd.DataFrame, charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for chart in charts:
        agg = _AGG_FUNCS.get(str(chart.get("agg", "sum")).lower(), "sum")
        value_column = chart.get("value_column")
        category_column = chart.get("category_column")
        date_column = chart.get("date_column")
        chart_type = str(chart.get("type", "bar")).lower()
        if chart_type not in {"bar", "line", "pie"}:
            chart_type = "bar"
        if value_column not in df.columns:
            continue
        if date_column and date_column not in df.columns:
            date_column = None
        if category_column and category_column not in df.columns:
            category_column = None
        if not date_column and not category_column:
            continue
        valid.append(
            {
                **chart,
                "agg": agg,
                "type": chart_type,
                "value_column": value_column,
                "category_column": category_column,
                "date_column": date_column,
            }
        )
    return valid[:4]


def compute_chart_series(df: pd.DataFrame, chart: dict[str, Any]) -> pd.Series:
    values = pd.to_numeric(df[chart["value_column"]], errors="coerce")
    if chart["date_column"]:
        dates = pd.to_datetime(df[chart["date_column"]], errors="coerce")
        grouped = values.groupby(dates.dt.to_period(chart.get("freq", "M") or "M"))
        series = getattr(grouped, chart["agg"])().dropna()
        series.index = series.index.astype(str)
        return series.tail(24)
    grouped = values.groupby(df[chart["category_column"]])
    series = getattr(grouped, chart["agg"])().dropna().sort_values(ascending=False)
    return series.head(10)


def _style_header_row(ws, row: int, n_cols: int) -> None:
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")


def _write_kpi_cards(ws, kpis: list[dict[str, Any]], values: list[float | int], start_row: int) -> int:
    ws.cell(row=start_row, column=1, value="KEY METRICS").font = _SECTION_FONT
    row = start_row + 2
    per_row = 4
    card_width = 2
    gap = 1
    for i, (kpi, value) in enumerate(zip(kpis, values)):
        block = i % per_row
        if i > 0 and block == 0:
            row += 4
        col = 1 + block * (card_width + gap)
        fill = PatternFill("solid", fgColor=PALETTE[i % len(PALETTE)])
        label_cell = ws.cell(row=row, column=col, value=str(kpi.get("name", "KPI")).upper())
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + card_width - 1)
        label_cell.font = _KPI_LABEL_FONT
        value_cell = ws.cell(row=row + 1, column=col, value=format_kpi_value(value, kpi.get("format")))
        ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 2, end_column=col + card_width - 1)
        value_cell.font = _KPI_VALUE_FONT
        value_cell.alignment = Alignment(vertical="center")
        for r in (row, row + 1, row + 2):
            for c in range(col, col + card_width):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor="F6F5F2")
        ws.cell(row=row, column=col).fill = fill
        ws.cell(row=row, column=col + card_width - 1).fill = fill
    return row + 4


def _write_bullets(ws, title: str, items: list[str], start_row: int, color: str = "12131C") -> int:
    if not items:
        return start_row
    ws.cell(row=start_row, column=1, value=title.upper()).font = _SECTION_FONT
    row = start_row + 1
    for item in items:
        cell = ws.cell(row=row, column=1, value=f"• {item}")
        cell.font = Font(size=11, color=color)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        ws.row_dimensions[row].height = 18
        row += 1
    return row + 1


def _build_overview_sheet(wb: Workbook, plan: dict[str, Any], df: pd.DataFrame, kpis: list[dict], kpi_values: list) -> None:
    ws = wb.active
    ws.title = "Overview"
    ws.sheet_view.showGridLines = False
    for col, width in zip("ABCDEFGH", [16, 16, 4, 16, 16, 4, 16, 16]):
        ws.column_dimensions[col].width = width

    ws.cell(row=1, column=1, value=f"DataMind — {plan.get('dataset_classification', 'Dataset')} Dashboard").font = _TITLE_FONT
    ws.merge_cells("A1:H1")
    ws.cell(row=2, column=1, value=f"{len(df):,} rows · {len(df.columns)} columns").font = _SUBTITLE_FONT
    ws.merge_cells("A2:H2")

    row = 4
    summary = plan.get("executive_summary")
    if summary:
        ws.cell(row=row, column=1, value="EXECUTIVE SUMMARY").font = _SECTION_FONT
        row += 1
        cell = ws.cell(row=row, column=1, value=summary)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=8)
        ws.row_dimensions[row].height = 20
        row += 4

    row = _write_kpi_cards(ws, kpis, kpi_values, row)
    row = _write_bullets(ws, "Key Insights", plan.get("insights_text", []), row)
    row = _write_bullets(ws, "Risks", plan.get("risks", []), row, color="B91C1C")
    row = _write_bullets(ws, "Opportunities", plan.get("opportunities", []), row, color="0D9488")

    recs = plan.get("recommendations", [])
    if recs:
        ws.cell(row=row, column=1, value="RECOMMENDATIONS").font = _SECTION_FONT
        row += 1
        headers = ["Action", "Priority", "Expected Impact"]
        for c, h in enumerate(headers, start=1):
            ws.cell(row=row, column=c, value=h)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=8)
        _style_header_row(ws, row, 3)
        row += 1
        for rec in recs:
            ws.cell(row=row, column=1, value=rec.get("action", ""))
            ws.cell(row=row, column=2, value=rec.get("priority", ""))
            impact_cell = ws.cell(row=row, column=3, value=rec.get("impact", ""))
            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=8)
            impact_cell.alignment = Alignment(wrap_text=True)
            row += 1


def _write_chart_block(ws, chart_spec: dict, series: pd.Series, start_row: int, index: int) -> int:
    ws.cell(row=start_row, column=1, value=chart_spec.get("title", "Chart")).font = _SECTION_FONT
    header_row = start_row + 1
    ws.cell(row=header_row, column=1, value="Category")
    ws.cell(row=header_row, column=2, value="Value")
    _style_header_row(ws, header_row, 2)

    for i, (label, value) in enumerate(series.items()):
        r = header_row + 1 + i
        ws.cell(row=r, column=1, value=str(label))
        ws.cell(row=r, column=2, value=float(value))

    n = len(series)
    data_ref = Reference(ws, min_col=2, min_row=header_row, max_row=header_row + n)
    cat_ref = Reference(ws, min_col=1, min_row=header_row + 1, max_row=header_row + n)

    chart_type = chart_spec["type"]
    chart = {"bar": BarChart, "line": LineChart, "pie": PieChart}[chart_type]()
    chart.title = chart_spec.get("title", "Chart")
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cat_ref)
    chart.style = 10
    chart.height = 8
    chart.width = 15
    if chart_type != "pie":
        chart.y_axis.majorGridlines = None
        series_obj = chart.series[0]
        series_obj.graphicalProperties.solidFill = PALETTE[index % len(PALETTE)]
    ws.add_chart(chart, f"D{start_row}")

    return header_row + max(n, 8) + 3


def _build_dashboard_sheet(wb: Workbook, charts: list[dict], df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 14
    row = 2
    for i, spec in enumerate(charts):
        series = compute_chart_series(df, spec)
        if series.empty:
            continue
        row = _write_chart_block(ws, spec, series, row, i)


def _build_data_sheet(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Data")
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(["" if pd.isna(v) else (str(v) if not isinstance(v, (int, float)) else v) for v in row])

    n_rows = len(df) + 1
    n_cols = len(df.columns)
    last_col = get_column_letter(n_cols)
    table = Table(displayName="DataMindData", ref=f"A1:{last_col}{n_rows}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False
    )
    ws.add_table(table)
    ws.freeze_panes = "A2"
    for col in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16


def _dax_measure(kpi: dict[str, Any]) -> str:
    name = kpi.get("name", "Measure").replace(" ", "_")
    column = kpi.get("column")
    agg = kpi.get("agg", "sum")
    dax_func = {"sum": "SUM", "mean": "AVERAGE", "median": "MEDIAN", "max": "MAX", "min": "MIN", "nunique": "DISTINCTCOUNT"}
    if agg == "row_count" or not column:
        return f"{name} = COUNTROWS(Data)"
    func = dax_func.get(agg, "SUM")
    return f"{name} = {func}(Data[{column}])"


def _build_powerbi_sheet(wb: Workbook, plan: dict[str, Any], kpis: list[dict]) -> None:
    ws = wb.create_sheet("Power BI Guide")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 90
    ws.cell(row=1, column=1, value="Recreating this dashboard in Power BI").font = _TITLE_FONT
    row = 3
    steps = [
        "1. Power BI Desktop -> Get Data -> Excel workbook -> select this file -> load the 'Data' table.",
        "2. Home -> Manage Relationships / New Measure to add the DAX measures below to the Data table.",
        "3. Recreate each chart on the Dashboard sheet as a matching Power BI visual (bar/line chart) "
        "using the same category and value fields.",
        "4. Add the measures as Card visuals across the top of the report page for the KPI row.",
    ]
    for step in steps:
        ws.cell(row=row, column=1, value=step).alignment = Alignment(wrap_text=True)
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="Suggested DAX measures").font = _SECTION_FONT
    row += 1
    for kpi in kpis:
        ws.cell(row=row, column=1, value=_dax_measure(kpi)).font = Font(name="Consolas", size=11)
        row += 1


def _build_notes_sheet(wb: Workbook, plan: dict[str, Any]) -> None:
    assumptions = plan.get("assumptions", [])
    limitations = plan.get("limitations", [])
    if not assumptions and not limitations:
        return
    ws = wb.create_sheet("Assumptions & Limitations")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 100
    row = _write_bullets(ws, "Assumptions", assumptions, 1)
    _write_bullets(ws, "Limitations", limitations, row)


def build_workbook(df: pd.DataFrame, plan: dict[str, Any]) -> Workbook:
    """Build the full multi-sheet Excel dashboard workbook from a dataframe and analysis plan.

    All KPI and chart values are computed here from `df` with pandas - the plan only
    supplies which columns/aggregations matter and the narrative text around them.
    """
    kpis = _valid_kpis(df, plan.get("kpis", []))
    kpi_values = [compute_kpi_value(df, k) for k in kpis]
    charts = _valid_charts(df, plan.get("charts", []))

    wb = Workbook()
    _build_overview_sheet(wb, plan, df, kpis, kpi_values)
    if charts:
        _build_dashboard_sheet(wb, charts, df)
    _build_data_sheet(wb, df)
    _build_powerbi_sheet(wb, plan, kpis)
    _build_notes_sheet(wb, plan)
    return wb
