# DataMind

DataMind turns a raw dataset into a real, downloadable **Excel dashboard** —
computed KPIs, native charts, a clean data table, and a Power BI/DAX guide —
plus a short plain-language summary of what's happening and what to do next.
It packages an **Advanced AI Data Analyst, Senior BI Developer, Data
Visualization Expert, and Dashboard UX/UI Designer** persona as a reusable
system prompt, profiles your dataset deterministically with pandas, and uses
Gemini to decide *which* KPIs/charts/insights matter for this dataset — but
every number in the output is computed by pandas against your actual data,
never taken verbatim from the model.

Uses the Gemini API (rather than a paid-only provider) so a free Google AI
Studio API key is enough to run this end to end, no billing setup required.

## How it works

1. `datamind/prompts/data_analyst_role.md` defines the full analyst role and
   44-phase workflow (data audit, cleaning, KPI discovery, trend/anomaly/
   root-cause analysis, forecasting, dashboard architecture, UI/UX design,
   documentation, ...). This is used verbatim as the model's system
   instruction.
2. `datamind/profiler.py` loads your dataset (CSV/TSV/JSON/Excel) and computes
   shape, dtypes, missingness, duplicates, and per-column statistics with
   pandas. This gives the model verified ground-truth facts instead of asking
   it to eyeball numbers from a raw preview.
3. `datamind/agent.py`'s `plan_dashboard()` sends the role prompt + dataset
   profile + your configuration to Gemini and gets back a compact JSON plan:
   which KPIs to show (column + aggregation, e.g. `sum(revenue)`), which
   charts to build (category/date column + value column), and short
   plain-language insights/risks/opportunities/recommendations. Column names
   in the plan are validated against the real dataset — anything that doesn't
   match an actual column is dropped rather than guessed at.
4. `datamind/dashboard.py` takes that plan and builds a **formula-driven**
   multi-sheet Excel workbook with `openpyxl` — the same architecture as a
   hand-built interactive Excel dashboard, not a snapshot of numbers:
   - **Dashboard**: title, up to 4 dropdown filters (data-validated against a
     hidden `Lists` sheet), 4 KPI cards wired to live formulas, and up to 5
     charts (a trend line, a doughnut for share-of-total, plain bar charts,
     and red/teal **diverging** bars for any metric whose per-category values
     can go negative, e.g. a margin or profit breakdown — decided from the
     real computed values, never from a guess).
   - **Calc**: the formula engine. Dropdown values resolve to `SUMIFS`/
     `AVERAGEIFS`/`COUNTIFS` wildcard filters (`"All"` → `"*"`), and every KPI
     card and chart is a live formula against **Data** — change a dropdown
     and everything recalculates, exactly like a real BI dashboard. (Two
     aggregations Excel has no `*IFS` form for — median, distinct count — fall
     back to a one-time computed value instead of a formula.)
   - **KPI Reference**: a definitions table (formula, why it matters, good vs.
     bad result, best visualization) plus the insights/risks/opportunities/
     prioritized recommendations.
   - **Data**: the full dataset as a real Excel Table, plus a derived
     `<column> (Month)` helper column for any date field used in a trend chart.
   - **Power BI Guide**: import steps + suggested DAX measures generated from
     the same KPI specs.
   - **Assumptions & Limitations**.
5. The web UI and CLI both also render/print a compact on-screen summary
   (KPI cards, insights, recommendations) computed once with pandas for
   display — independent of the workbook's live formulas — alongside the
   downloadable file. `agent.analyze()` is still available if you want the
   full 28-section narrative report as plain text instead.

## Setup

```bash
pip install -e ".[dev]"
export GEMINI_API_KEY=...
```

Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey)
— no billing setup required for the free tier (rate-limited).

## CLI usage

**Excel dashboard** (the primary output — computed KPIs, native charts, data table, Power BI guide):

```bash
datamind sample_data/sample_sales.csv \
  --tool Excel \
  --objective "Sales Analysis" \
  --audience CEO \
  --output-xlsx dashboard.xlsx
```

**Full narrative report** (the role's 28-section text deliverable, if you want that instead):

```bash
datamind sample_data/sample_sales.csv --depth "Standard Analysis" --output analysis.md
```

Run `datamind --help` for all options (business context, business questions,
primary goal, brand colors, dashboard style, a specific ad-hoc question, model
override, max tokens).

## Library usage

```python
from datamind import DataAnalystAgent, UserConfig, build_workbook, load_dataframe

agent = DataAnalystAgent()
config = UserConfig(
    preferred_tool="Power BI",
    analysis_depth="Deep Dive",
    dashboard_objective="Sales Analysis",
    target_audience="CEO",
)

# Real Excel dashboard: KPIs and charts computed from the actual data
plan = agent.plan_dashboard("sample_data/sample_sales.csv", config=config)
df = load_dataframe("sample_data/sample_sales.csv")
workbook = build_workbook(df, plan)
workbook.save("dashboard.xlsx")

# Or the full narrative report as plain text
report = agent.analyze("sample_data/sample_sales.csv", config=config)
print(report)
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
`datamind/dashboard.py`'s workbook building against the real sample dataset
(no mocking needed since it's pure pandas/openpyxl) — including an
independent formula interpreter that parses the generated `SUMIFS`/
`AVERAGEIFS`/`COUNTIFS` strings and re-evaluates them against the dataframe,
so a plausible-looking-but-wrong formula (bad column letter, off-by-one row
range) gets caught even though nothing in this environment can open the file
in real Excel/LibreOffice to check. The `/api/analyze` request/response
handling is covered too (with the Gemini call mocked). Nothing calls the
Gemini API.

## Web app / Vercel deployment

The same agent is exposed as a web app: a static UI at `index.html` and a
Python serverless function at `api/analyze.py` (plus `api/health.py` for a
readiness check). `POST /api/analyze` returns a compact JSON `summary` (for
the on-page KPI cards/insights) plus a base64-encoded `workbook_base64` — the
full Excel dashboard — which the browser decodes into a `Blob` and offers as
a one-click download. Vercel auto-detects the `api/*.py` files as serverless
functions and serves everything else as static assets — no framework or
build step needed.

**Deploy:**

```bash
npm install -g vercel   # one-time
vercel login
vercel link             # creates/links the Vercel project
vercel env add GEMINI_API_KEY production   # paste your key when prompted
vercel --prod
```

Or connect the GitHub repo in the Vercel dashboard (Import Project), then add
`GEMINI_API_KEY` under Project Settings → Environment Variables before the
first deploy. Environment variables only apply to deployments created after
they're saved — redeploy if you add or change one after the fact.

**Local dev with the Vercel CLI** (serves the static UI and the Python
functions together, matching production):

```bash
vercel dev
```

**Notes:**

- The Python runtime version is pinned via `.python-version` (3.12); function
  dependencies for Vercel are declared in the root `requirements.txt`
  (separate from `pyproject.toml`, which is for local/CLI installs).
- The web form accepts CSV, TSV, JSON, and Excel (.xlsx/.xls/.xlsm) as input,
  capped at 4 MB client-side (a generous margin under the platform's request
  body limit). Text formats are read and posted as UTF-8; Excel files are
  read as bytes, base64-encoded, and posted with `"encoding": "base64"` -
  `/api/analyze` decodes accordingly before handing the file to pandas. The
  *output* is always a real `.xlsx` workbook regardless of input format.
- The frontend never calls `response.json()` directly on a fetch response -
  it reads the body as text first and parses that, so a non-JSON response
  (a platform-level crash page, a timeout, a rejected oversized payload -
  none of which come from our own handler) surfaces as a clear, bounded
  error message instead of an opaque "Unexpected token ... is not valid
  JSON" thrown straight out of a failed `.json()` call.
- There's no reliable way to generate a real `.pbix` (Power BI's binary
  project format) from Python, so "Power BI" support means: import the
  `Data` sheet of the generated workbook into Power BI Desktop, then use the
  `Power BI Guide` sheet's ready-made DAX measures and chart-recreation
  steps — not a literal `.pbix` file.
- `vercel.json` sets `maxDuration: 60` for the API functions, since an LLM
  analysis call can take longer than the platform's 10s default. Hobby plans
  cap function duration at 60s; for `Deep Dive` analyses on large datasets you
  may need a Pro plan for a longer duration.
- `GET /api/health` returns `{"status": "ok", "gemini_api_key_configured": true|false}`
  so you can confirm the deployment is wired up correctly without running a
  full analysis.
- The Gemini free tier is rate-limited (requests per minute/day); if you hit
  those limits, the analysis call will fail with an error from the API — wait
  and retry, or switch to a paid Gemini tier for higher limits.

## Project layout

```
index.html                       # static web UI (upload dataset, configure, run analysis, download xlsx)
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
  agent.py                       # DataAnalystAgent: plan_dashboard() (JSON plan) + analyze() (narrative)
  dashboard.py                   # builds the formula-driven Excel workbook (openpyxl): Dashboard/Calc/KPI Reference/Data/Power BI Guide
  cli.py                         # `datamind` command-line entry point
sample_data/sample_sales.csv
tests/
```
