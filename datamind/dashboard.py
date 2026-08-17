"""Builds a real, downloadable, formula-driven Excel dashboard from a dataset and plan.

The analysis plan (see agent.DataAnalystAgent.plan_dashboard) tells this module which
KPIs/charts/filters matter and how to compute them (column + aggregation), but the
Dashboard sheet is wired up as live Excel formulas (SUMIFS/AVERAGEIFS/COUNTIFS) against
the Data sheet, filtered by dropdown cells resolved on the Calc sheet - the same
architecture as a hand-built interactive Excel dashboard: change a dropdown and every
KPI card and chart recalculates. Nothing on the Dashboard is a hardcoded snapshot
number (a small number of aggregations Excel has no *IFS form for - median, distinct
count - fall back to a plain computed value, clearly labeled).

Sheets produced: Dashboard (filters, KPI cards, charts), KPI Reference (definitions +
insights/risks/opportunities/recommendations), Data (the cleaned dataset as an Excel
Table, plus derived month columns for any date-based chart), Calc (the formula engine),
Power BI Guide (import steps + DAX measures), Assumptions & Limitations, and a hidden
Lists sheet backing the filter dropdowns.
"""

import re
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from datamind.profiler import load_dataframe as _load_dataframe

PALETTE = ["4338CA", "0D9488", "D97706", "7C3AED", "DC2626", "2563EB"]
POS_COLOR = "0D9488"
NEG_COLOR = "DC2626"

MAX_FILTER_COLUMNS = 4
MAX_KPIS = 8
MAX_DASHBOARD_KPIS = 4
MAX_CHARTS = 5
MAX_CATEGORY_ROWS = 12

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
_IFS_FUNC = {"sum": "SUMIFS", "mean": "AVERAGEIFS", "max": "MAXIFS", "min": "MINIFS"}
_PLAIN_FUNC = {"sum": "SUM", "mean": "AVERAGE", "max": "MAX", "min": "MIN"}
_FORMULA_UNSUPPORTED_AGGS = {"median", "nunique"}

_NUMBER_FORMATS = {
    "currency": '"$"#,##0',
    "percent": "0.0%",
    "number": "#,##0",
}

_HEADER_FILL = PatternFill("solid", fgColor="12131C")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
_TITLE_FONT = Font(bold=True, size=16, color="12131C")
_SUBTITLE_FONT = Font(size=11, color="5A5D72")
_LABEL_FONT = Font(size=10.5, bold=True, color="12131C")
_KPI_LABEL_FONT = Font(size=10, bold=True, color="5A5D72")
_KPI_VALUE_FONT = Font(size=20, bold=True, color="12131C")
_KPI_CAPTION_FONT = Font(size=9.5, color="5A5D72")
_SECTION_FONT = Font(size=13, bold=True, color="12131C")
_CARD_BG = PatternFill("solid", fgColor="F6F5F2")


def load_dataframe(path: str | Path) -> pd.DataFrame:
    """Load a dataset the same way datamind.profiler does, for reuse by the dashboard builder."""
    return _load_dataframe(path)


def _abs_ref(cell: str) -> str:
    match = re.match(r"([A-Z]+)(\d+)", cell)
    return f"${match.group(1)}${match.group(2)}"


def _style_header_row(ws, row: int, n_cols: int) -> None:
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT


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


# ---------------------------------------------------------------------------
# Plan validation + pandas computations shared with the on-page (non-Excel) summary
# ---------------------------------------------------------------------------


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
    return valid[:MAX_KPIS]


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

    Used for the on-page (non-Excel) summary. Independent of the Excel formula engine
    below, which recomputes everything live inside the workbook instead.
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


def _valid_filter_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    valid = []
    for col in columns or []:
        if col in df.columns and col not in valid:
            series = df[col]
            if not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series):
                valid.append(col)
    return valid[:MAX_FILTER_COLUMNS]


def _valid_charts(df: pd.DataFrame, charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for chart in charts:
        agg = _AGG_FUNCS.get(str(chart.get("agg", "sum")).lower(), "sum")
        value_column = chart.get("value_column")
        category_column = chart.get("category_column")
        date_column = chart.get("date_column")
        if value_column not in df.columns or agg in _FORMULA_UNSUPPORTED_AGGS:
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
                "value_column": value_column,
                "category_column": category_column,
                "date_column": date_column,
            }
        )
    return valid[:MAX_CHARTS]


def compute_chart_series(df: pd.DataFrame, chart: dict[str, Any]) -> pd.Series:
    values = pd.to_numeric(df[chart["value_column"]], errors="coerce")
    if chart["date_column"]:
        dates = pd.to_datetime(df[chart["date_column"]], errors="coerce")
        grouped = values.groupby(dates.dt.to_period(chart.get("freq", "M") or "M"))
        series = getattr(grouped, chart["agg"])().dropna()
        series.index = series.index.astype(str)
        return series.tail(24)
    grouped = values.groupby(df[chart["category_column"]])
    series = getattr(grouped, chart["agg"])().dropna().sort_values(key=abs, ascending=False)
    return series.head(MAX_CATEGORY_ROWS)


def _classify_charts(df: pd.DataFrame, charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decide each chart's rendering kind (trend/doughnut/diverging/bar) from the real
    data - never from the model's chart-type guess. The attached series is used only to
    decide category order/labels/count; the workbook's own values come from live
    formulas built later, not from this series."""
    classified = []
    for chart in charts:
        series = compute_chart_series(df, chart)
        if series.empty:
            continue
        if chart["date_column"]:
            kind = "trend"
        elif (series < 0).any():
            kind = "diverging"
        elif len(series) <= 6 and str(chart.get("type", "")).lower() in {"pie", "doughnut"}:
            kind = "doughnut"
        else:
            kind = "bar"
        classified.append({**chart, "kind": kind, "series": series})
    return classified


def _place_charts(charts: list[dict[str, Any]]) -> dict[str, Any]:
    """Adaptive slot assignment: a trend chart (or first remaining) goes top-left wide,
    a doughnut-eligible chart (or first remaining) goes top-right, everything else
    fills up to 3 bottom slots - mirroring a hand-built dashboard's layout instincts."""
    remaining = list(charts)

    def _take(predicate):
        for i, c in enumerate(remaining):
            if predicate(c):
                return remaining.pop(i)
        return remaining.pop(0) if remaining else None

    top_left = _take(lambda c: c["kind"] == "trend")
    top_right = _take(lambda c: c["kind"] == "doughnut")
    bottom = remaining[:3]
    return {"top_left": top_left, "top_right": top_right, "bottom": bottom}


def _month_column_name(date_column: str) -> str:
    return f"{date_column} (Month)"


# ---------------------------------------------------------------------------
# Data sheet
# ---------------------------------------------------------------------------


def _build_data_sheet(wb: Workbook, df: pd.DataFrame, month_columns: list[str]) -> dict[str, str]:
    ws = wb.create_sheet("Data")

    if month_columns:
        extra = pd.DataFrame(
            {
                _month_column_name(col): pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m")
                for col in month_columns
            }
        )
        full = pd.concat([df.reset_index(drop=True), extra], axis=1)
    else:
        full = df

    ws.append(list(full.columns))
    for row in full.itertuples(index=False):
        ws.append(["" if pd.isna(v) else (str(v) if not isinstance(v, (int, float)) else v) for v in row])

    n_rows = len(full) + 1
    n_cols = len(full.columns)
    last_col = get_column_letter(n_cols)
    table = Table(displayName="DataMindData", ref=f"A1:{last_col}{n_rows}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False)
    ws.add_table(table)
    ws.freeze_panes = "A2"
    for col in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    return {name: get_column_letter(i + 1) for i, name in enumerate(full.columns)}


# ---------------------------------------------------------------------------
# Lists sheet (hidden) - backs the dropdown data validation on the Dashboard sheet
# ---------------------------------------------------------------------------


def _defined_name_for(col: str, index: int) -> str:
    """A valid, collision-free Excel defined-name for a filter's dropdown list.

    Data validation lists that reference another sheet directly (formula1 pointing at
    e.g. "Lists!$A$1:$A$8") are a well-documented Excel compatibility trap - some
    versions/viewers silently refuse the cross-sheet reference. A workbook-scoped
    defined name pointing at that same range is the universally supported way to back
    a cross-sheet dropdown, so every filter gets one instead.
    """
    base = re.sub(r"[^A-Za-z0-9_]", "_", col).strip("_") or "Filter"
    if not (base[0].isalpha() or base[0] == "_"):
        base = f"_{base}"
    return f"DM_Filter_{index}_{base}"[:200]


def _build_lists_sheet(wb: Workbook, df: pd.DataFrame, filter_columns: list[str]) -> dict[str, str]:
    ws = wb.create_sheet("Lists")
    ws.sheet_state = "hidden"
    defined_names: dict[str, str] = {}
    for i, col in enumerate(filter_columns):
        letter = get_column_letter(i + 1)
        values = list(df[col].astype(str).value_counts().head(MAX_CATEGORY_ROWS).index)
        ws.cell(row=1, column=i + 1, value="All")
        for r, v in enumerate(values, start=2):
            ws.cell(row=r, column=i + 1, value=v)
        name = _defined_name_for(col, i)
        wb.defined_names[name] = DefinedName(name=name, attr_text=f"Lists!${letter}$1:${letter}${1 + len(values)}")
        defined_names[col] = name
    return defined_names


# ---------------------------------------------------------------------------
# Dashboard filter cell layout (pure - no dependency on Calc/Data build order)
# ---------------------------------------------------------------------------


def _dashboard_filter_layout(filter_columns: list[str]) -> dict[str, dict[str, str]]:
    layout = {}
    for i, col in enumerate(filter_columns):
        base = 2 + 3 * i  # B=2, E=5, H=8, K=11
        layout[col] = {
            "label_cell": f"{get_column_letter(base)}4",
            "value_cell": f"{get_column_letter(base + 1)}4",
        }
    return layout


# ---------------------------------------------------------------------------
# Calc sheet - the formula engine
# ---------------------------------------------------------------------------


def _ifs_formula(agg: str, value_letter: str | None, n_rows: int, criteria: list[tuple[str, str]]) -> str:
    if agg == "row_count":
        if not criteria:
            return f"=COUNTA(Data!$A$2:$A${n_rows + 1})"
        parts = []
        for letter, crit in criteria:
            parts += [f"Data!${letter}$2:${letter}${n_rows + 1}", crit]
        return f"=COUNTIFS({','.join(parts)})"

    if not criteria:
        func = _PLAIN_FUNC[agg]
        return f"={func}(Data!${value_letter}$2:${value_letter}${n_rows + 1})"

    func = _IFS_FUNC[agg]
    parts = [f"Data!${value_letter}$2:${value_letter}${n_rows + 1}"]
    for letter, crit in criteria:
        parts += [f"Data!${letter}$2:${letter}${n_rows + 1}", crit]
    return f"={func}({','.join(parts)})"


def _write_breakdown_table(
    ws,
    chart: dict[str, Any],
    col_letters: dict[str, str],
    filter_columns: list[str],
    filter_resolved: dict[str, str],
    n_rows: int,
    start_row: int,
) -> dict[str, Any]:
    kind = chart["kind"]
    series = chart["series"]
    agg = chart["agg"]
    value_letter = col_letters[chart["value_column"]]
    axis_col_name = _month_column_name(chart["date_column"]) if chart["date_column"] else chart["category_column"]
    axis_letter = col_letters[axis_col_name]

    ws.cell(row=start_row, column=1, value=chart.get("title", "Chart")).font = _LABEL_FONT
    header_row = start_row + 1
    headers = ["Category", "Value"] + (["Pos", "Neg"] if kind == "diverging" else [])
    for c, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c, value=h)
    _style_header_row(ws, header_row, len(headers))

    cross_filter_cols = [c for c in filter_columns if c != axis_col_name]
    labels = list(series.index) if chart["date_column"] else list(series.index)

    first_data_row = header_row + 1
    for i, label in enumerate(labels):
        r = first_data_row + i
        ws.cell(row=r, column=1, value=str(label))
        own_criterion = (axis_letter, f"$A{r}")
        criteria = [own_criterion] + [(col_letters[c], filter_resolved[c]) for c in cross_filter_cols]
        formula = _ifs_formula(agg, value_letter, n_rows, criteria)
        ws.cell(row=r, column=2, value=formula)
        if kind == "diverging":
            ws.cell(row=r, column=3, value=f"=IF(B{r}>=0,B{r},0)")
            ws.cell(row=r, column=4, value=f"=IF(B{r}<0,B{r},0)")

    last_data_row = first_data_row + len(labels) - 1
    return {
        "chart": chart,
        "kind": kind,
        "header_row": header_row,
        "first_data_row": first_data_row,
        "last_data_row": last_data_row,
        "next_row": last_data_row + 2,
    }


def _build_calc_sheet(
    wb: Workbook,
    df: pd.DataFrame,
    col_letters: dict[str, str],
    filter_columns: list[str],
    filter_dash_cells: dict[str, dict[str, str]],
    kpis: list[dict[str, Any]],
    dashboard_charts: list[dict[str, Any]],
    n_rows: int,
) -> dict[str, Any]:
    ws = wb.create_sheet("Calc")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 22
    for col in "BCDE":
        ws.column_dimensions[col].width = 15

    ws.cell(
        row=1, column=1, value="Calculation engine (feeds the Dashboard; formulas only, no hardcoded numbers)"
    ).font = _SECTION_FONT

    row = 3
    filter_resolved: dict[str, str] = {}
    if filter_columns:
        ws.cell(row=row, column=1, value="Resolved filters (helper - do not edit)").font = _LABEL_FONT
        row += 1
        for col in filter_columns:
            dash_ref = _abs_ref(filter_dash_cells[col]["value_cell"])
            ws.cell(row=row, column=1, value=f"{col} filter")
            ws.cell(row=row, column=2, value=f'=IF(Dashboard!{dash_ref}="All","*",Dashboard!{dash_ref})')
            filter_resolved[col] = f"Calc!{_abs_ref(f'B{row}')}"
            row += 1
        row += 1

    ws.cell(row=row, column=1, value="Key metrics (respect all filters above)").font = _LABEL_FONT
    row += 1
    kpi_rows = []
    for kpi in kpis:
        ws.cell(row=row, column=1, value=kpi.get("name", "KPI"))
        agg = kpi["agg"]
        if agg in _FORMULA_UNSUPPORTED_AGGS:
            value = compute_kpi_value(df, kpi)
            ws.cell(row=row, column=2, value=float(value))
            is_formula = False
        else:
            value_letter = col_letters.get(kpi["column"]) if kpi["column"] else None
            criteria = [(col_letters[c], filter_resolved[c]) for c in filter_columns]
            ws.cell(row=row, column=2, value=_ifs_formula(agg, value_letter, n_rows, criteria))
            is_formula = True
        ws.cell(row=row, column=2).number_format = _NUMBER_FORMATS.get((kpi.get("format") or "number").lower(), "#,##0")
        kpi_rows.append({"kpi": kpi, "row": row, "is_formula": is_formula})
        row += 1
    row += 1

    chart_tables = []
    for chart in dashboard_charts:
        table = _write_breakdown_table(ws, chart, col_letters, filter_columns, filter_resolved, n_rows, row)
        chart_tables.append(table)
        row = table["next_row"]

    return {"filter_resolved": filter_resolved, "kpi_rows": kpi_rows, "chart_tables": chart_tables}


# ---------------------------------------------------------------------------
# Dashboard sheet
# ---------------------------------------------------------------------------


def _build_chart(calc_ws, table: dict[str, Any]) -> Any:
    kind = table["kind"]
    header_row = table["header_row"]
    first = table["first_data_row"]
    last = table["last_data_row"]
    title = table["chart"].get("title", "Chart")
    cat_ref = Reference(calc_ws, min_col=1, min_row=first, max_row=last)

    if kind == "diverging":
        chart = BarChart()
        chart.type = "bar"
        chart.grouping = "stacked"
        chart.overlap = 100
        chart.add_data(Reference(calc_ws, min_col=3, min_row=header_row, max_row=last), titles_from_data=True)
        chart.add_data(Reference(calc_ws, min_col=4, min_row=header_row, max_row=last), titles_from_data=True)
        chart.set_categories(cat_ref)
        chart.series[0].graphicalProperties.solidFill = POS_COLOR
        chart.series[1].graphicalProperties.solidFill = NEG_COLOR
        chart.y_axis.majorGridlines = None
    elif kind == "doughnut":
        chart = DoughnutChart()
        chart.add_data(Reference(calc_ws, min_col=2, min_row=header_row, max_row=last), titles_from_data=True)
        chart.set_categories(cat_ref)
        n_slices = last - header_row
        chart.series[0].data_points = [
            DataPoint(idx=i, spPr=GraphicalProperties(solidFill=PALETTE[i % len(PALETTE)])) for i in range(n_slices)
        ]
    elif kind == "trend":
        chart = LineChart()
        chart.add_data(Reference(calc_ws, min_col=2, min_row=header_row, max_row=last), titles_from_data=True)
        chart.set_categories(cat_ref)
        chart.series[0].graphicalProperties.line.solidFill = PALETTE[0]
        chart.series[0].graphicalProperties.line.width = 24000
        chart.y_axis.majorGridlines = None
    else:
        chart = BarChart()
        chart.type = "col"
        chart.add_data(Reference(calc_ws, min_col=2, min_row=header_row, max_row=last), titles_from_data=True)
        chart.set_categories(cat_ref)
        chart.series[0].graphicalProperties.solidFill = PALETTE[1]
        chart.y_axis.majorGridlines = None

    chart.title = title
    chart.style = 10
    return chart


def _write_kpi_cards(ws, kpi_rows: list[dict[str, Any]], start_row: int = 6) -> None:
    for i, entry in enumerate(kpi_rows[:MAX_DASHBOARD_KPIS]):
        kpi = entry["kpi"]
        base = 2 + 3 * i
        accent = PALETTE[i % len(PALETTE)]
        top_border = Border(top=Side(style="medium", color=accent))

        label_cell = ws.cell(row=start_row, column=base, value=str(kpi.get("name", "KPI")).upper())
        ws.merge_cells(start_row=start_row, start_column=base, end_row=start_row, end_column=base + 1)
        label_cell.font = _KPI_LABEL_FONT
        label_cell.border = top_border
        ws.cell(row=start_row, column=base + 1).border = top_border

        kpi_row = entry["row"]
        value_cell = ws.cell(row=start_row + 1, column=base, value=f"=Calc!{_abs_ref(f'B{kpi_row}')}")
        ws.merge_cells(start_row=start_row + 1, start_column=base, end_row=start_row + 1, end_column=base + 1)
        value_cell.font = _KPI_VALUE_FONT
        value_cell.number_format = _NUMBER_FORMATS.get((kpi.get("format") or "number").lower(), "#,##0")

        meaning = kpi.get("meaning")
        if meaning:
            cap = ws.cell(row=start_row + 2, column=base, value=meaning)
            ws.merge_cells(start_row=start_row + 2, start_column=base, end_row=start_row + 2, end_column=base + 1)
            cap.font = _KPI_CAPTION_FONT
            cap.alignment = Alignment(wrap_text=True)


GRID_COLS = 24  # 0-indexed Dashboard grid columns (0..23) that charts are placed within
CHART_TOP_ROW = 10  # 0-indexed; row 11 one-indexed, below the KPI cards
CHART_TOP_HEIGHT = 17
CHART_ROW_GAP = 2


def _two_cell_anchor(min_col: int, min_row: int, max_col: int, max_row: int) -> TwoCellAnchor:
    """A chart anchor bound to an exact grid-cell range, not a floating cm size.

    Two charts placed via disjoint column/row ranges can never visually overlap,
    regardless of the sheet's actual column widths - unlike a single-cell anchor with
    a cm width/height, which floats over the grid and can drift into a neighboring
    chart's space depending on how wide the underlying columns happen to be.
    """
    return TwoCellAnchor(_from=AnchorMarker(col=min_col, row=min_row), to=AnchorMarker(col=max_col, row=max_row))


def _split_columns(n: int, total: int = GRID_COLS, gap: int = 2) -> list[tuple[int, int]]:
    if n <= 0:
        return []
    width = (total - gap * (n - 1)) // n
    spans = []
    start = 0
    for _ in range(n):
        end = start + width
        spans.append((start, end))
        start = end + gap
    return spans


def _build_dashboard_sheet(
    wb: Workbook,
    plan: dict[str, Any],
    df: pd.DataFrame,
    filter_columns: list[str],
    filter_dash_cells: dict[str, dict[str, str]],
    filter_dropdown_names: dict[str, str],
    calc: dict[str, Any],
    placed: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2.5
    for i in range(4):
        base = 2 + 3 * i
        ws.column_dimensions[get_column_letter(base)].width = 17
        ws.column_dimensions[get_column_letter(base + 1)].width = 17
        ws.column_dimensions[get_column_letter(base + 2)].width = 3
    last_col = get_column_letter(2 + 3 * 4 - 1)

    ws.cell(row=1, column=1, value=f"{plan.get('dataset_classification', 'Dataset')} — Dashboard").font = _TITLE_FONT
    ws.merge_cells(f"A1:{last_col}1")
    ws.cell(row=2, column=1, value=f"{len(df):,} records").font = _SUBTITLE_FONT
    ws.merge_cells(f"A2:{last_col}2")

    for col in filter_columns:
        cells = filter_dash_cells[col]
        label_cell = ws[cells["label_cell"]]
        label_cell.value = f"{col}:"
        label_cell.font = _LABEL_FONT
        value_cell = ws[cells["value_cell"]]
        value_cell.value = "All"
        value_cell.fill = _CARD_BG
        dv = DataValidation(type="list", formula1=filter_dropdown_names[col], allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(value_cell)

    _write_kpi_cards(ws, calc["kpi_rows"], start_row=6)

    calc_ws = wb["Calc"]
    table_by_chart_id = {id(t["chart"]): t for t in calc["chart_tables"]}

    def _anchor(chart_spec, min_col, min_row, max_col, max_row):
        if chart_spec is None:
            return
        chart_obj = _build_chart(calc_ws, table_by_chart_id[id(chart_spec)])
        ws.add_chart(chart_obj, anchor=_two_cell_anchor(min_col, min_row, max_col, max_row))

    top_row_end = CHART_TOP_ROW + CHART_TOP_HEIGHT
    top_left = placed["top_left"]
    top_right = placed["top_right"]
    top_charts = [c for c in (top_left, top_right) if c is not None]
    if top_left is not None and top_right is not None:
        top_spans = [(0, GRID_COLS // 2 - 1), (GRID_COLS // 2 + 1, GRID_COLS - 1)]
    elif top_charts:
        top_spans = [(0, GRID_COLS - 1)]
    else:
        top_spans = []
    for chart_spec, (c0, c1) in zip(top_charts, top_spans):
        _anchor(chart_spec, c0, CHART_TOP_ROW, c1, top_row_end)

    bottom = placed["bottom"]
    bottom_row_start = top_row_end + CHART_ROW_GAP
    bottom_row_end = bottom_row_start + CHART_TOP_HEIGHT
    for chart_spec, (c0, c1) in zip(bottom, _split_columns(len(bottom))):
        _anchor(chart_spec, c0, bottom_row_start, c1, bottom_row_end)


# ---------------------------------------------------------------------------
# KPI Reference sheet
# ---------------------------------------------------------------------------


def _build_kpi_reference_sheet(wb: Workbook, plan: dict[str, Any], kpis: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet("KPI Reference")
    ws.sheet_view.showGridLines = False
    for col, width in zip("ABCDEFG", [22, 32, 28, 32, 26, 26, 24]):
        ws.column_dimensions[col].width = width

    ws.cell(row=1, column=1, value=f"{plan.get('dataset_classification', 'Dataset')} — KPI Reference").font = _TITLE_FONT
    ws.merge_cells("A1:G1")
    row = 3
    headers = ["KPI", "Definition", "Formula", "Why it matters", "Good result", "Bad result", "Best visualization"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    _style_header_row(ws, row, len(headers))
    row += 1

    for kpi in kpis:
        agg = kpi.get("agg", "sum")
        column = kpi.get("column")
        default_formula = "COUNT(rows)" if agg == "row_count" else f"{agg.upper()}({column})"
        values = [
            kpi.get("name", "KPI"),
            kpi.get("definition") or kpi.get("meaning", ""),
            kpi.get("formula_text") or default_formula,
            kpi.get("why_it_matters", ""),
            kpi.get("good_result", ""),
            kpi.get("bad_result", ""),
            kpi.get("best_visualization", ""),
        ]
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 1

    row += 1
    row = _write_bullets(ws, "Key Insights", plan.get("insights_text", []), row)
    row = _write_bullets(ws, "Risks", plan.get("risks", []), row, color="B91C1C")
    row = _write_bullets(ws, "Opportunities", plan.get("opportunities", []), row, color="0D9488")

    recs = plan.get("recommendations", [])
    if recs:
        ws.cell(row=row, column=1, value="RECOMMENDATIONS").font = _SECTION_FONT
        row += 1
        rec_headers = ["Action", "Priority", "Expected Impact"]
        for c, h in enumerate(rec_headers, start=1):
            ws.cell(row=row, column=c, value=h)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        _style_header_row(ws, row, 3)
        row += 1
        for rec in recs:
            ws.cell(row=row, column=1, value=rec.get("action", ""))
            ws.cell(row=row, column=2, value=rec.get("priority", ""))
            impact_cell = ws.cell(row=row, column=3, value=rec.get("impact", ""))
            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
            impact_cell.alignment = Alignment(wrap_text=True)
            row += 1


# ---------------------------------------------------------------------------
# Power BI Guide + Assumptions & Limitations
# ---------------------------------------------------------------------------


def _dax_measure(kpi: dict[str, Any]) -> str:
    name = str(kpi.get("name", "Measure")).replace(" ", "_")
    column = kpi.get("column")
    agg = kpi.get("agg", "sum")
    dax_func = {"sum": "SUM", "mean": "AVERAGE", "median": "MEDIAN", "max": "MAX", "min": "MIN", "nunique": "DISTINCTCOUNT"}
    if agg == "row_count" or not column:
        return f"{name} = COUNTROWS(Data)"
    func = dax_func.get(agg, "SUM")
    return f"{name} = {func}(Data[{column}])"


def _build_powerbi_sheet(wb: Workbook, plan: dict[str, Any], kpis: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet("Power BI Guide")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 90
    ws.cell(row=1, column=1, value="Recreating this dashboard in Power BI").font = _TITLE_FONT
    row = 3
    steps = [
        "1. Power BI Desktop -> Get Data -> Excel workbook -> select this file -> load the 'Data' table.",
        "2. Home -> Manage Relationships / New Measure to add the DAX measures below to the Data table.",
        "3. Recreate each chart on the Dashboard sheet as a matching Power BI visual (bar/line/donut) "
        "using the same category and value fields, and add slicers for the filter columns.",
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_SHEET_ORDER = ["Dashboard", "KPI Reference", "Data", "Calc", "Power BI Guide", "Assumptions & Limitations", "Lists"]


def build_workbook(df: pd.DataFrame, plan: dict[str, Any]) -> Workbook:
    """Build the full multi-sheet, formula-driven Excel dashboard workbook.

    KPI/chart *structure* (which columns, which aggregations, which filters) comes from
    the plan; every number the workbook actually displays is a live Excel formula
    against the Data sheet (or, for the handful of aggregations Excel has no *IFS form
    for, a clearly-scoped one-time pandas computation) - never a value taken from the
    model directly.
    """
    kpis = _valid_kpis(df, plan.get("kpis", []))
    filter_columns = _valid_filter_columns(df, plan.get("filter_columns", []))
    raw_charts = _valid_charts(df, plan.get("charts", []))
    classified = _classify_charts(df, raw_charts)
    placed = _place_charts(classified)
    dashboard_charts = [c for c in [placed["top_left"], placed["top_right"], *placed["bottom"]] if c is not None]

    month_columns = sorted({c["date_column"] for c in dashboard_charts if c["date_column"]})
    n_rows = len(df)

    wb = Workbook()
    wb.remove(wb.active)

    col_letters = _build_data_sheet(wb, df, month_columns)
    filter_dropdown_names = _build_lists_sheet(wb, df, filter_columns) if filter_columns else {}
    filter_dash_cells = _dashboard_filter_layout(filter_columns)
    calc = _build_calc_sheet(wb, df, col_letters, filter_columns, filter_dash_cells, kpis, dashboard_charts, n_rows)
    _build_dashboard_sheet(wb, plan, df, filter_columns, filter_dash_cells, filter_dropdown_names, calc, placed)
    _build_kpi_reference_sheet(wb, plan, kpis)
    _build_powerbi_sheet(wb, plan, kpis)
    _build_notes_sheet(wb, plan)

    wb.calculation.fullCalcOnLoad = True
    wb._sheets = [wb[name] for name in _SHEET_ORDER if name in wb.sheetnames]
    wb.active = 0

    return wb
