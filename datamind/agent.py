import json
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from datamind.config import UserConfig
from datamind.profiler import format_profile_summary, profile_dataset
from datamind.role import load_role_prompt

DEFAULT_MODEL = os.environ.get("DATAMIND_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_TOKENS = 8192

_DASHBOARD_PLAN_INSTRUCTIONS = """
# OUTPUT FORMAT — DASHBOARD PLAN (this overrides the "Final Deliverable" narrative format)

Apply your full analytical process (dataset classification, KPI discovery, EDA,
trend/anomaly/root-cause analysis, risks, opportunities, recommendations) internally,
but respond with ONLY a single JSON object (no markdown, no code fences, no commentary)
matching exactly this shape:

{{
  "dataset_classification": "short label, e.g. Sales",
  "executive_summary": "2-4 plain-language sentences on what's happening and why it matters",
  "kpis": [
    {{"name": "Total Revenue", "column": "<exact column name from the dataset>", "agg": "sum", "format": "currency", "meaning": "one line"}}
  ],
  "charts": [
    {{"title": "Revenue by Region", "type": "bar", "category_column": "<exact column name>", "value_column": "<exact column name>", "agg": "sum"}},
    {{"title": "Revenue Trend", "type": "line", "date_column": "<exact column name>", "value_column": "<exact column name>", "agg": "sum", "freq": "M"}}
  ],
  "insights_text": ["3-6 short, plain-language insight sentences, each standalone"],
  "risks": ["short plain-language risk statements"],
  "opportunities": ["short plain-language opportunity statements"],
  "recommendations": [{{"action": "specific action", "priority": "High|Medium|Low", "impact": "expected business impact, one line"}}],
  "assumptions": ["short assumption statements"],
  "limitations": ["what this dataset cannot answer"]
}}

Rules:
- "column", "category_column", "value_column", "date_column" MUST be exact column
  names copied verbatim from the DATASET PROFILE below — never invented or renamed.
- "agg" MUST be one of: sum, mean, median, max, min, count, nunique, row_count.
  Use "row_count" with no column for a plain row-count KPI (e.g. Total Orders).
- "format" MUST be one of: currency, percent, number. Only use "percent" for a
  column stored as a 0-1 fraction (e.g. a 0.1 discount rate) — it will be
  displayed multiplied by 100, matching spreadsheet percent formatting.
- 4-8 kpis, 1-4 charts, each insight/risk/opportunity a single short sentence —
  write for someone with no data background, not a technical audience.
- Every claim must be traceable to the dataset profile; never fabricate numbers.
""".strip()


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


class DataAnalystAgent:
    """Runs the Advanced AI Data Analyst role against a dataset via the Gemini API.

    The role prompt (datamind/prompts/data_analyst_role.md) is used verbatim as the
    system instruction. The dataset is profiled deterministically first (see
    datamind.profiler) so the model works from verified facts about shape, dtypes,
    missingness, and distributions rather than re-deriving them, then produces either
    a full narrative report (analyze) or a compact structured plan (plan_dashboard)
    that datamind.dashboard turns into a real Excel workbook with computed KPIs and
    native charts.

    Uses Gemini (rather than a paid-only API) so the free tier of a Google AI Studio
    API key is enough to run this end to end with no billing setup.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.model = model
        self.system_prompt = load_role_prompt()

    def _brief_and_profile(
        self, dataset_path: str | Path, config: UserConfig | None, question: str | None
    ) -> tuple[str, str]:
        config = config or UserConfig()
        profile = profile_dataset(dataset_path)
        sections = [config.to_brief(), format_profile_summary(profile)]
        if question:
            sections.append(f"# SPECIFIC QUESTION\n{question}")
        return "\n\n".join(sections), format_profile_summary(profile)

    def build_user_message(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
    ) -> str:
        brief, _ = self._brief_and_profile(dataset_path, config, question)
        return (
            f"{brief}\n\n"
            "Proceed autonomously through the full workflow defined in your role "
            "instructions and produce the Final Deliverable."
        )

    def build_dashboard_message(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
    ) -> str:
        brief, _ = self._brief_and_profile(dataset_path, config, question)
        return f"{brief}\n\n{_DASHBOARD_PLAN_INSTRUCTIONS}"

    def analyze(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Full narrative report following the role's 28-section Final Deliverable."""
        user_message = self.build_user_message(dataset_path, config, question)
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text

    def plan_dashboard(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """Compact structured plan (KPIs, charts, insights) for datamind.dashboard to render
        into a real Excel workbook with pandas-computed values and native charts."""
        user_message = self.build_dashboard_message(dataset_path, config, question)
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        )
        return _extract_json(response.text)
