import argparse
import sys
from pathlib import Path

from datamind.agent import DEFAULT_MODEL, DataAnalystAgent
from datamind.config import (
    DEFAULT_ANALYSIS_DEPTH,
    VALID_ANALYSIS_DEPTHS,
    VALID_DASHBOARD_OBJECTIVES,
    VALID_TARGET_AUDIENCES,
    VALID_TOOLS,
    UserConfig,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datamind",
        description="Run the Advanced AI Data Analyst role against a dataset.",
    )
    parser.add_argument("dataset", help="Path to a CSV, TSV, JSON, or Excel file")
    parser.add_argument(
        "--tool",
        default="Python",
        choices=sorted(VALID_TOOLS),
        help="Preferred BI tool (default: Python)",
    )
    parser.add_argument(
        "--depth",
        default=DEFAULT_ANALYSIS_DEPTH,
        choices=sorted(VALID_ANALYSIS_DEPTHS),
        help=f"Analysis depth (default: {DEFAULT_ANALYSIS_DEPTH})",
    )
    parser.add_argument("--objective", choices=sorted(VALID_DASHBOARD_OBJECTIVES), default=None)
    parser.add_argument("--audience", choices=sorted(VALID_TARGET_AUDIENCES), default=None)
    parser.add_argument("--context", default=None, help="Business context")
    parser.add_argument("--questions", default=None, help="Business questions to prioritize")
    parser.add_argument("--goal", default=None, help="Primary goal")
    parser.add_argument("--brand-colors", default=None)
    parser.add_argument("--style", default=None, help="Preferred dashboard style")
    parser.add_argument("--question", default=None, help="A specific ad-hoc question to answer")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--output", default=None, help="Write the narrative report to this file instead of stdout")
    parser.add_argument(
        "--output-xlsx",
        default=None,
        help=(
            "Write a real Excel dashboard (computed KPIs, native charts, cleaned "
            "data table, Power BI/DAX guide) to this path instead of the narrative report"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = UserConfig(
        preferred_tool=args.tool,
        analysis_depth=args.depth,
        dashboard_objective=args.objective,
        business_context=args.context,
        business_questions=args.questions,
        primary_goal=args.goal,
        target_audience=args.audience,
        brand_colors=args.brand_colors,
        preferred_style=args.style,
    )

    agent = DataAnalystAgent(model=args.model)

    if args.output_xlsx:
        from datamind.dashboard import build_workbook, load_dataframe

        plan = agent.plan_dashboard(
            dataset_path=args.dataset,
            config=config,
            question=args.question,
            max_tokens=args.max_tokens,
        )
        df = load_dataframe(args.dataset)
        workbook = build_workbook(df, plan)
        workbook.save(args.output_xlsx)
        print(f"Wrote Excel dashboard to {args.output_xlsx}")
        return 0

    result = agent.analyze(
        dataset_path=args.dataset,
        config=config,
        question=args.question,
        max_tokens=args.max_tokens,
    )

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"Wrote analysis to {args.output}")
    else:
        print(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
