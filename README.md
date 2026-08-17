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

Tests cover the deterministic dataset profiler, configuration validation, and
the `/api/analyze` request/response handling (with the Claude call mocked);
they do not call the Claude API.

## Web app / Vercel deployment

The same agent is exposed as a web app: a static UI at `index.html` and a
Python serverless function at `api/analyze.py` (plus `api/health.py` for a
readiness check). Vercel auto-detects the `api/*.py` files as serverless
functions and serves everything else as static assets — no framework or
build step needed.

**Deploy:**

```bash
npm install -g vercel   # one-time
vercel login
vercel link             # creates/links the Vercel project
vercel env add ANTHROPIC_API_KEY production   # paste your key when prompted
vercel --prod
```

Or connect the GitHub repo in the Vercel dashboard (Import Project), then add
`ANTHROPIC_API_KEY` under Project Settings → Environment Variables before the
first deploy.

**Local dev with the Vercel CLI** (serves the static UI and the Python
functions together, matching production):

```bash
vercel dev
```

**Notes:**

- The Python runtime version is pinned via `.python-version` (3.12); function
  dependencies for Vercel are declared in the root `requirements.txt`
  (separate from `pyproject.toml`, which is for local/CLI installs and also
  includes `openpyxl` for Excel support that the CLI has but the web form
  does not).
- The web form accepts CSV/TSV/JSON only, read client-side as text and posted
  as JSON to `/api/analyze`. Excel files are only supported via the
  `datamind` CLI/library.
- `vercel.json` sets `maxDuration: 60` for the API functions, since an LLM
  analysis call can take longer than the platform's 10s default. Hobby plans
  cap function duration at 60s; for `Deep Dive` analyses on large datasets you
  may need a Pro plan for a longer duration.
- `GET /api/health` returns `{"status": "ok", "anthropic_api_key_configured": true|false}`
  so you can confirm the deployment is wired up correctly without running a
  full analysis.

## Project layout

```
index.html                       # static web UI (upload dataset, configure, run analysis)
api/
  analyze.py                     # POST /api/analyze - Vercel Python serverless function
  health.py                      # GET /api/health - readiness check
vercel.json                      # function config (maxDuration)
requirements.txt                 # Python deps for the Vercel build
.python-version                  # pins the Vercel Python runtime version
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
