# DataMind

DataMind turns a raw dataset into a decision-making system, not just a pile of
charts. It packages an **Advanced AI Data Analyst, Senior BI Developer, Data
Visualization Expert, and Dashboard UX/UI Designer** persona as a reusable
system prompt, profiles your dataset deterministically with pandas, and sends
both to Claude to produce a full dataset audit, KPI set, EDA, trend/anomaly/
root-cause analysis, dashboard design, and prioritized recommendations.

## How it works

1. `datamind/prompts/data_analyst_role.md` defines the full analyst role and
   44-phase workflow (data audit, cleaning, KPI discovery, trend/anomaly/
   root-cause analysis, forecasting, dashboard architecture, UI/UX design,
   documentation, presentation talking points, stakeholder Q&A, ...). This is
   used verbatim as the model's system prompt.
2. `datamind/profiler.py` loads your dataset (CSV/TSV/JSON/Excel) and computes
   shape, dtypes, missingness, duplicates, and per-column statistics with
   pandas. This gives the model verified ground-truth facts instead of asking
   it to eyeball numbers from a raw preview.
3. `datamind/agent.py` combines the role prompt, your configuration (preferred
   tool, analysis depth, dashboard objective, business context, target
   audience, brand style), and the dataset profile into a single request to
   the Claude API, and returns the full analysis.

## Setup

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...
```

## CLI usage

```bash
datamind sample_data/sample_sales.csv \
  --tool Python \
  --depth "Standard Analysis" \
  --objective "Sales Analysis" \
  --audience CEO \
  --output analysis.md
```

Run `datamind --help` for all options (business context, business questions,
primary goal, brand colors, dashboard style, a specific ad-hoc question, model
override, max tokens).

## Library usage

```python
from datamind import DataAnalystAgent, UserConfig

agent = DataAnalystAgent()
config = UserConfig(
    preferred_tool="Power BI",
    analysis_depth="Deep Dive",
    dashboard_objective="Sales Analysis",
    target_audience="CEO",
)
result = agent.analyze("sample_data/sample_sales.csv", config=config)
print(result)
```

## Sample data

`sample_data/sample_sales.csv` is a small retail orders dataset (region,
category, product, revenue, cost, discount) you can use to try the agent
before pointing it at your own data.

## Testing

```bash
pytest
```

Tests cover the deterministic dataset profiler and configuration validation;
they do not call the Claude API.

## Project layout

```
datamind/
  prompts/data_analyst_role.md   # the analyst persona / system prompt
  role.py                        # loads the role prompt
  config.py                      # UserConfig: tool, depth, objective, context
  profiler.py                    # deterministic dataset profiling (pandas)
  agent.py                       # DataAnalystAgent: wires prompt + profile -> Claude
  cli.py                         # `datamind` command-line entry point
sample_data/sample_sales.csv
tests/
```
