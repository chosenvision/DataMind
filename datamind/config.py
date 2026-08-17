from dataclasses import dataclass, field

DEFAULT_ANALYSIS_DEPTH = "Standard Analysis"

VALID_TOOLS = {
    "Excel",
    "Power BI",
    "Google Sheets",
    "Tableau",
    "Looker Studio",
    "Python",
    "SQL + BI Tool",
    "Other",
}

VALID_ANALYSIS_DEPTHS = {
    "Quick Analysis",
    "Standard Analysis",
    "Deep Dive",
    "Executive Mode",
    "Data Analyst Mode",
}

VALID_DASHBOARD_OBJECTIVES = {
    "Executive Overview",
    "Sales Analysis",
    "Marketing Analysis",
    "Financial Analysis",
    "Customer Analysis",
    "E-Commerce Analysis",
    "Social Media Analysis",
    "Operations Analysis",
    "HR Analysis",
    "Product Analysis",
    "Forecasting",
    "Performance Monitoring",
    "Custom",
}

VALID_TARGET_AUDIENCES = {
    "CEO",
    "Management",
    "Finance",
    "Marketing",
    "Sales",
    "Operations",
    "Analysts",
    "Other",
}


@dataclass
class UserConfig:
    """User-selectable configuration for a DataMind analysis run.

    Any field left as None is intentionally left for the agent to infer from the
    dataset, per the role's instruction to never stop the workflow on missing input.
    """

    preferred_tool: str = "Python"
    analysis_depth: str = DEFAULT_ANALYSIS_DEPTH
    dashboard_objective: str | None = None
    business_context: str | None = None
    business_questions: str | None = None
    primary_goal: str | None = None
    target_audience: str | None = None
    brand_colors: str | None = None
    preferred_style: str | None = None
    extra_notes: str | None = None

    def __post_init__(self) -> None:
        if self.preferred_tool not in VALID_TOOLS:
            raise ValueError(
                f"preferred_tool must be one of {sorted(VALID_TOOLS)}, got {self.preferred_tool!r}"
            )
        if self.analysis_depth not in VALID_ANALYSIS_DEPTHS:
            raise ValueError(
                f"analysis_depth must be one of {sorted(VALID_ANALYSIS_DEPTHS)}, "
                f"got {self.analysis_depth!r}"
            )
        if self.dashboard_objective is not None and self.dashboard_objective not in VALID_DASHBOARD_OBJECTIVES:
            raise ValueError(
                f"dashboard_objective must be one of {sorted(VALID_DASHBOARD_OBJECTIVES)}, "
                f"got {self.dashboard_objective!r}"
            )
        if self.target_audience is not None and self.target_audience not in VALID_TARGET_AUDIENCES:
            raise ValueError(
                f"target_audience must be one of {sorted(VALID_TARGET_AUDIENCES)}, "
                f"got {self.target_audience!r}"
            )

    def to_brief(self) -> str:
        """Render this configuration as the USER CONFIGURATION block for the agent."""
        lines = [
            "# USER CONFIGURATION",
            f"Preferred Tool: {self.preferred_tool}",
            f"Analysis Depth: {self.analysis_depth}",
            f"Dashboard Objective: {self.dashboard_objective or 'Not specified - infer from dataset'}",
            f"Target Audience: {self.target_audience or 'Not specified'}",
            f"Preferred Dashboard Style: {self.preferred_style or 'Not specified - choose a professional palette'}",
            f"Brand Colors: {self.brand_colors or 'Not specified'}",
        ]
        if self.business_context:
            lines.append(f"Business Context: {self.business_context}")
        if self.business_questions:
            lines.append(f"Business Questions: {self.business_questions}")
        if self.primary_goal:
            lines.append(f"Primary Goal: {self.primary_goal}")
        if self.extra_notes:
            lines.append(f"Additional Notes: {self.extra_notes}")
        return "\n".join(lines)
