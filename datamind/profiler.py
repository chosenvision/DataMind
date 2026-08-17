from pathlib import Path
from typing import Any

import pandas as pd

MAX_CATEGORY_VALUES = 10
MAX_PREVIEW_ROWS = 5

_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}


def _read_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in _EXCEL_SUFFIXES:
        return pd.read_excel(path)
    if path.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t")
    if path.suffix.lower() == ".json":
        return pd.read_json(path)
    return pd.read_csv(path)


def _column_profile(series: pd.Series) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "dtype": str(series.dtype),
        "missing_count": int(series.isna().sum()),
        "missing_pct": round(float(series.isna().mean()) * 100, 2),
        "unique_count": int(series.nunique(dropna=True)),
    }

    if pd.api.types.is_numeric_dtype(series):
        described = series.describe()
        profile["stats"] = {
            "min": _safe_float(described.get("min")),
            "max": _safe_float(described.get("max")),
            "mean": _safe_float(described.get("mean")),
            "median": _safe_float(series.median()),
            "std": _safe_float(described.get("std")),
        }
        profile["negative_count"] = int((series < 0).sum())
        profile["zero_count"] = int((series == 0).sum())
    elif pd.api.types.is_datetime64_any_dtype(series):
        profile["min_date"] = str(series.min())
        profile["max_date"] = str(series.max())
    else:
        top_values = series.value_counts(dropna=True).head(MAX_CATEGORY_VALUES)
        profile["top_values"] = {str(k): int(v) for k, v in top_values.items()}

    return profile


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def profile_dataset(path: str | Path) -> dict[str, Any]:
    """Load a dataset (CSV/TSV/Excel/JSON) and build a structured data quality profile.

    This mirrors the Dataset Overview and Data Quality Audit phases of the
    Advanced AI Data Analyst role: shape, dtypes, missingness, duplicates, and
    per-column statistics, produced deterministically so the language model
    reasons over verified facts rather than re-deriving them from raw rows.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = _read_any(path)

    duplicate_rows = int(df.duplicated().sum())

    columns = {col: _column_profile(df[col]) for col in df.columns}

    return {
        "source_file": str(path),
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "duplicate_row_count": duplicate_rows,
        "columns": columns,
        "preview": df.head(MAX_PREVIEW_ROWS).to_dict(orient="records"),
    }


def format_profile_summary(profile: dict[str, Any]) -> str:
    """Render a profile dict as a compact markdown block suitable for an LLM prompt."""
    lines = [
        "# DATASET PROFILE (computed deterministically - treat as ground truth)",
        f"Source file: {profile['source_file']}",
        f"Rows: {profile['row_count']}",
        f"Columns: {profile['column_count']}",
        f"Duplicate rows: {profile['duplicate_row_count']}",
        "",
        "## Columns",
    ]
    for name, col in profile["columns"].items():
        lines.append(
            f"- `{name}` ({col['dtype']}): "
            f"{col['missing_count']} missing ({col['missing_pct']}%), "
            f"{col['unique_count']} unique"
        )
        if "stats" in col:
            stats = col["stats"]
            lines.append(
                f"    min={stats['min']} max={stats['max']} mean={stats['mean']} "
                f"median={stats['median']} std={stats['std']} "
                f"negatives={col['negative_count']} zeros={col['zero_count']}"
            )
        elif "top_values" in col:
            top = ", ".join(f"{k} ({v})" for k, v in col["top_values"].items())
            lines.append(f"    top values: {top}")
        elif "min_date" in col:
            lines.append(f"    range: {col['min_date']} to {col['max_date']}")

    lines.append("")
    lines.append("## Preview rows")
    for row in profile["preview"]:
        lines.append(f"- {row}")

    return "\n".join(lines)
