# Lakeflow Designer: silver to gold without code

**Audience:** analytics team (beginner to intermediate SQL, limited Python)

Designer is the closest equivalent to the visual ETL tooling an analytics team is likely using
today, and it answers the question that matters most for your team directly: **can a non-technical
user create and maintain a client pipeline.**

## Scope: this guide covers the silver-to-gold half of notebook 04

Notebook 04 runs raw → bronze → silver → gold. **Designer picks up at silver.** Be clear on the
split, because it is a boundary worth knowing before you hit it:

| Stage | Where it lives | Why |
|---|---|---|
| Raw → bronze: union sources, deduplicate | **Notebook 04** | Needs `ROW_NUMBER() OVER (PARTITION BY ...)`. Designer has no window-function operator |
| Bronze → silver: standardise, flag quality | **Notebook 04** | Built alongside the dedupe, in the same notebook |
| Filling the FX weekend gaps | **Notebook 03** | Needs `LAST_VALUE(...) IGNORE NULLS OVER (...)`, another window function |
| **Silver → gold: filter, convert currency** | **Designer** | An ordinary filter, join and formula. Part 1, Pipeline A |
| **Reporting aggregates and league tables** | **Designer** | Group-by and derived columns. Part 1, Pipelines B and C |
| Onboarding a client by config | **Notebook 05** | Runs the notebooks above with a different `client_id` |
| Calling an API | Either, see Part 4 | Possible in Designer via a Python operator, but the notebook is the better home |

**What that means in practice:** the stages that stay in code are the window operations, which are
exactly the class of thing visual ETL tools do not express. This is a capability boundary, not a gap
in the guide.

**What that means in practice for your team:** the analytics team owns the gold layer and everything
downstream of it, which is where their day-to-day requests actually land: add a column, add a
source, change a rule, build a new summary. Bronze and silver are built once by engineering and
then rarely touched. So the honest claim is not "no engineers needed", it is **"no engineer needed
for the work that recurs"**, which is the stronger claim anyway.

Pipeline A below reads `dq_status` and `dq_flags` from the silver table. Those columns are
*created* by notebook 04, so **notebook 04 must have run first**.

---

## Part 1: Building the gold layer, node by node

Target: from `03_silver.silver_<client>_performance` to a gold master table plus the
reporting aggregates, with no Python.

### Pipeline A: gold master table

```
[1] Source                 03_silver.silver_northwind_retail_performance
       |
[2] Filter                 dq_status = 'valid'
       |
[3] Source (second input)  01_raw.fx_daily_rates
       |
[4] Join                   left join, silver.currency = fx.base_currency
                                  AND silver.report_date = fx.rate_date
       |
[5] Formula                spend_usd = round(spend * rate_to_usd, 2)
       |
[6] Select                 keep and rename the master-table columns
       |
[7] Output                 04_gold.gold_northwind_retail_master   (mode: overwrite)
```

**Node by node:**

| # | Operator | Configuration | Why |
|---|---|---|---|
| 1 | **Source** | Browse to the silver table | Designer reads UC tables directly |
| 2 | **Filter** | `dq_status = 'valid'` | Flagged rows stay in silver for review, they do not reach gold |
| 3 | **Source** | `01_raw.fx_daily_rates` | Produced by notebook 03. Use this, **not** `raw_fx_rates`: it already has a rate for every calendar day, so weekends are covered |
| 4 | **Join** | Type: **Left**. Keys as above | Left, not inner: a missing FX rate must never silently drop a row of spend |
| 5 | **Formula** | One expression as above | No `coalesce` needed. Defaulting a missing rate to 1.0 would report GBP spend as though it were USD |
| 6 | **Select** | Rename `spend` to `spend_local`, `currency` to `local_currency` | Makes the currency of each figure unambiguous |
| 7 | **Output** | Target table, overwrite | Overwrite is fine for a full rebuild; see the note on incremental below |

### Pipeline B: reporting aggregates

```
[1] Source     04_gold.gold_northwind_retail_master
       |
[2] Aggregate  group by: client_id, platform, report_date
               measures: sum(impressions), sum(clicks), sum(conversions), sum(spend_usd)
       |
[3] Formula    ctr_pct = round(clicks * 100.0 / nullif(impressions, 0), 3)
               cpa_usd = round(spend_usd / nullif(conversions, 0), 2)
       |
[4] Output     04_gold.gold_northwind_retail_daily_summary
```

**The one thing to get right here:** compute CTR and CPA **after** aggregating, from the
summed totals. Averaging the per-row `ctr_pct` gives a different and wrong answer, because
it weights a campaign with 200 impressions the same as one with 200,000. This is the same
rule encoded in the Genie measures and in the dashboard datasets, and it is the most common
analytical error in this domain.

### Pipeline C: campaign league table

```
[1] Source     04_gold.gold_northwind_retail_master
       |
[2] Aggregate  group by: campaign_id, campaign_name, platform
               measures: sum(impressions), sum(clicks), sum(conversions), sum(spend_usd)
       |
[3] Formula    ctr_pct, cpa_usd  (as above)
       |
[4] Filter     impressions > 1000
       |
[5] Sort       cpa_usd ascending
       |
[6] Output     04_gold.gold_northwind_retail_campaign_performance
```

The `impressions > 1000` filter is not arbitrary: without a floor, a campaign with 3
impressions and 1 click shows a 33 percent CTR and tops the league table. Any efficiency
ranking needs a minimum volume threshold to be meaningful.

---

## Part 2: Genie Code prompts

Designer includes Genie Code, which builds nodes from a natural-language description. These
prompts are written to produce the pipelines above. Paste one, then **check the generated
nodes against the tables in Part 1** rather than trusting the output.

### Prompt 1: the gold master table

```
Build a data preparation pipeline that produces a consolidated client master table.

Read from enablement.03_silver.silver_northwind_retail_performance and keep only rows
where dq_status equals 'valid'.

Left join to enablement.01_raw.fx_daily_rates, matching the silver currency column to
base_currency and report_date to rate_date. Use a left join so no spend rows are lost
when a rate is missing.

Add one calculated column:
  spend_usd = round(spend * rate_to_usd, 2)

Rename spend to spend_local and currency to local_currency.

Output these columns to enablement.04_gold.gold_northwind_retail_master:
client_id, platform, campaign_id, campaign_name, report_date, impressions, clicks,
conversions, spend_local, local_currency, rate_to_usd as fx_rate_to_usd, spend_usd
```

### Prompt 2: daily summary

```
From enablement.04_gold.gold_northwind_retail_master, create a daily summary grouped by
client_id, platform and report_date.

Sum impressions, clicks, conversions and spend_usd.

Then calculate, from the summed totals rather than by averaging existing ratio columns:
  ctr_pct = round(sum_clicks * 100.0 / nullif(sum_impressions, 0), 3)
  cpa_usd = round(sum_spend_usd / nullif(sum_conversions, 0), 2)

It is important that CTR and CPA are recalculated after aggregation, not averaged.

Write the result to enablement.04_gold.gold_northwind_retail_daily_summary
```

### Prompt 3: campaign league table

```
From enablement.04_gold.gold_northwind_retail_master, build a campaign efficiency ranking.

Group by campaign_id, campaign_name and platform. Sum impressions, clicks, conversions
and spend_usd.

Calculate ctr_pct and cpa_usd from the summed totals using nullif to avoid divide by zero.

Exclude campaigns with 1000 or fewer total impressions, because small volumes produce
misleading efficiency ratios.

Sort by cpa_usd ascending so the most efficient campaigns appear first.

Write to enablement.04_gold.gold_northwind_retail_campaign_performance
```

### Prompt 4: data quality summary

```
From enablement.03_silver.silver_northwind_retail_performance, build a data quality
summary for operations.

Group by dq_status and platform, and count the rows.

Separately, produce a detail output of every row where dq_status = 'flagged', keeping
report_date, platform, campaign_id, campaign_name, spend and dq_flags, sorted by
report_date.

Write the summary to enablement.05_ops.dq_summary_by_platform and the detail to
enablement.05_ops.dq_review_queue
```

---

## Part 3: Routine maintenance, the non-technical path

Worth practising each one.

### Adding a column

1. Open the visual data prep file.
2. Click the **Select** node.
3. Tick the new column so it flows through.
4. If it needs calculating, add it in the **Formula** node instead.
5. **Run** to preview, then **Publish**.

### Adding a source

1. Drag a new **Source** node onto the canvas and point it at the new table or volume path.
2. Add a **Join** or **Union** node to combine it with the existing flow.
   - **Union** when the new source has the same shape, for example another ad platform.
   - **Join** when it adds columns, for example a lookup table.
3. Preview to confirm the row count moves as you expect, then publish.

A word of caution on Union: confirm the column names and types line up first. A silent
mismatch produces nulls rather than an error, and nulls are much harder to notice than a
failure.

### Schema changes

Designer picks up new columns from the source when you refresh the node. The
`addNewColumns` setting on Auto Loader has already handled the raw layer, so a new
platform column appears in silver automatically and Designer only needs the Select node
updated.

### Investigating a failure

1. Open the run history on the data prep file.
2. Click the failed node. The error appears with a preview of the offending rows.
3. Use **Rows scanned: sample** while iterating; it is much faster.
4. Fix and re-run.

Note the documented caveat: running with **Rows scanned: Max** reprocesses the full
unbounded dataset and can take a long time. Use sample mode while building.

### Reloading after a fix

Designer's output modes are overwrite and append. Overwrite is what this build uses everywhere, so
correcting bad data is just re-running the pipeline: it rebuilds from source, and Delta keeps the
previous version if the reload turns out to be wrong.

Insert-or-replace on a key, so a daily run touches only the days that changed, is a `MERGE`. That is
a job rather than a Designer node, and it is a topic for a later session.

---

## Part 4: API ingestion inside Designer

**Optional, and not needed for the session.** This is a ceiling-of-capability answer for when
someone asks "could we pull the API in here too", not a day-one workflow.

There is **no built-in "call an API" source node.** The documented sources are Unity Catalog
tables, UC volumes and folder paths, local file upload, Google Drive, SharePoint and metric views
([source](https://docs.databricks.com/aws/en/designer/ingest-data)).

But Designer supports **user-defined operators**, and one of the three types is a general-purpose
Python block, so API ingestion is genuinely possible. Two routes, differing in capability:

| | Route A: `python-run-function` | Route B: `uc-udf` (SQL) |
|---|---|---|
| Language | Python | SQL, or Python wrapped in SQL |
| Receives | `config`, `inputs` (DataFrames), `spark` | Column values |
| Returns | DataFrames | A single value |
| HTTP calls | Any library, e.g. `requests` | `http_request()` only |
| Third-party packages | Yes, via `environment` in the YAML | No |
| **Reads secret scopes** | **Yes**, `DBUtils(spark).secrets.get()` | No |
| Uses UC connections | Not needed | Yes, required |
| Governed by | Workspace file permissions | UC `EXECUTE` + `USE SCHEMA` |

**Route A is the one to build.** The real distinction is not "Designer versus notebooks" but
"Python operator versus SQL operator": a Python operator reads the same secret scope notebook 02
creates, so there is one credential store rather than two. Only a SQL UDF needs a UC connection,
because it cannot reach `dbutils`.

---

### Route A: a Python operator (recommended)

A `python-run-function` operator gets `run(config, inputs, spark)`, so it has the full
SparkSession, can pip-install any package, and can read a secret scope directly. This is the
same code and the same credential store as a notebook.

#### The YAML

`config` fields become widgets in the operator UI, which is what lets a non-technical user
point the operator at a different client or credential without editing code.

```yaml
schema: user-defined-operator-v0.1.0
type: python-run-function
name: Fetch FX Rates
id: fetch_fx_rates
description: Pull a daily FX series from an API into a DataFrame.
version: 1

# Third-party packages. This is what makes `requests` available.
environment:
  dependencies:
    - requests==2.31.0

config:
  - name: base_currency
    label: Base currency
    type: string
    default: GBP
  - name: quote_currency
    label: Quote currency
    type: string
    default: USD
  - name: start_date
    label: Start date (YYYY-MM-DD)
    type: string
  - name: end_date
    label: End date (YYYY-MM-DD)
    type: string
  # The NAMES of the secret, not the secret. The operator resolves it at runtime, so a
  # non-technical user picks a credential without ever seeing its value.
  - name: secret_scope
    label: Secret scope
    type: string
    default: enablement_demo
  - name: secret_key
    label: Secret key
    type: string
    default: api_token_via_py_sdk

outputs:
  - name: rates
```

#### The Python

```python
def run(config, inputs, spark):
    import requests
    from pyspark.dbutils import DBUtils

    # The secret scope from notebook 02. One credential store, not two.
    dbutils = DBUtils(spark)
    token = dbutils.secrets.get(
        scope=config["secret_scope"],
        key=config["secret_key"],
    )

    base = config["base_currency"]
    quote = config["quote_currency"]

    resp = requests.get(
        f"https://api.frankfurter.dev/v1/{config['start_date']}..{config['end_date']}",
        params={"base": base, "symbols": quote},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    # Fail loudly. Returning an empty DataFrame would make a broken credential look
    # identical to a day with no data, which is the failure nobody notices.
    if resp.status_code != 200:
        raise RuntimeError(f"FX API returned HTTP {resp.status_code}: {resp.text[:200]}")

    payload = resp.json()
    if "rates" not in payload:
        raise RuntimeError(f"Unexpected response shape: {str(payload)[:200]}")

    rows = [
        {
            "pair": f"{base}/{quote}",
            "base_currency": base,
            "quote_currency": quote,
            "rate_date": day,
            "rate_close": float(vals[quote]),
        }
        for day, vals in sorted(payload["rates"].items())
        if quote in vals
    ]

    if not rows:
        raise RuntimeError("API returned no rates for the requested window.")

    # Must return a dict whose keys match the `outputs` names in the YAML.
    return {"rates": spark.createDataFrame(rows)}
```

#### Using it on a canvas

The operator appears in the palette. Drop it in, fill the config fields, and wire its `rates`
output into a **Join** node against the silver data exactly as Pipeline A does. No SQL JSON
parsing and no Explode node, because it already returns proper rows.

**Why this is the better route:** ordinary Python, a real library, the same secret scope as the
notebook pipeline, and errors you can actually read.

---

### Route B: a SQL operator with `http_request()`

Worth knowing because it is the only option if you are restricted to SQL, and because it uses
UC connections, which govern the **host** as well as the credential.

```sql
-- run this once before using Route B; no notebook creates it for you
CREATE CONNECTION fx_api_conn
  TYPE HTTP
  OPTIONS (
    host 'https://api.frankfurter.dev',
    port '443',
    base_path '/v1/',
    bearer_token 'unused-but-required'   -- required by the type even when the API ignores it
  );

GRANT USE CONNECTION ON CONNECTION fx_api_conn TO `analysts`;
```

#### Where parameters go, and the one place they cannot go

`DESCRIBE FUNCTION EXTENDED http_request` gives the full signature:

```
http_request(conn, method, path, json, headers, params)
```

Verified against an echo endpoint, so this is what actually reaches the server:

| Put values in | Works | Arrives as |
|---|---|---|
| `params => map('start_date','2026-07-01', ...)` | **yes** | `?start_date=2026-07-01&...` on the URL |
| `json => '{"start_date":"2026-07-01"}'` with `method => 'POST'` | **yes** | request body, `content-type: application/json` |
| `headers => map(...)` | yes | request headers |
| A **path segment** containing `..` | **no** | rejected before the call is made |
| A `?query=string` appended to `path` | no | the `?` is escaped, so the server 404s |

The connection also injects `authorization: Bearer <token>` on every request automatically, which
is the point of it: the credential never appears in the query text.

So for **most** APIs, including the ad platforms you will actually be pulling from, a date range is
straightforward because they take dates as query parameters. This is the Facebook Insights
shape, which is the one that matters here:

```sql
http_request(
  conn   => 'facebook_conn',
  method => 'GET',
  path   => '/v21.0/act_123/insights',
  params => map(
    'time_range', '{"since":"2026-07-01","until":"2026-07-22"}',
    'fields',     'impressions,clicks,spend',
    'level',      'campaign'
  )
)
```

Verified against an echo endpoint: all three parameters arrive intact, including the nested JSON
in `time_range` (URL-encoded correctly on the way out). So the whole window comes back in **one**
call, exactly as Route A does it, with the token supplied by the connection rather than sitting
in the query text. **This is the version to show a SQL-only audience**, not the FX case below.

#### The Frankfurter quirk: a range in the *path*

Frankfurter is the awkward case, and it is worth knowing why so the limitation is not
misattributed to `http_request`. It takes its range as a **path segment**
(`/v1/2026-07-01..2026-07-22`), which is the one place `http_request` will not accept it:

```
[INVALID_HTTP_REQUEST_PATH] The input parameter: path, value: /2026-07-01..2026-07-03
is not a valid parameter for http_request because path traversal is not allowed.
```

The `..` is read as directory traversal and blocked, whether written literally or assembled with
`concat`. `%2E%2E` passes the check and then 404s. Frankfurter also ignores `start_date` when
sent as a query parameter or in the body, so for this specific API the range is genuinely
unreachable from SQL. The workaround is one call per date:

```sql
CREATE OR REPLACE FUNCTION enablement.05_ops.fetch_fx_rate(
  base STRING, quote STRING, on_date STRING
)
RETURNS STRING
RETURN http_request(
  conn   => 'fx_api_conn',
  method => 'GET',
  path   => concat('/', on_date),   -- single date, no ".." range
  params => map('base', base, 'symbols', quote)
).text;
```

Register it as a `uc-udf` operator. `http_request` returns
`STRUCT<status_code INT, text STRING>`, so the JSON still needs parsing, but a single-date
response is flat enough to read directly and needs no Explode node:

```sql
SELECT d AS report_date,
       get_json_object(fetch_fx_rate('GBP', 'USD', cast(d AS STRING)), '$.rates.USD') AS usd
FROM (SELECT explode(sequence(DATE'2026-07-01', DATE'2026-07-22')) AS d)
```

Verified: returns one row per date with real rates (1.324, 1.3306, 1.3355 for 1 to 3 July).

**Drawbacks versus Route A.** Note these are narrower than they first look, and only the first
is a real blocker:

- **SQL UDFs cannot read a secret scope** (they cannot reach `dbutils`), so the credential has
  to live in the connection. This is the genuine constraint that forces the two routes apart.
- JSON parsing happens in SQL, which is more awkward than `requests` plus a dict.
- The docs note `http_request` is **rate-limited and meant for interactive rather than
  high-volume batch use**. For Frankfurter specifically, the per-date workaround turns 1 call
  into 22, which leans on it in exactly the way it is not designed for. For a query-param API
  this does not apply.

Retries it *does* handle, contrary to what you might assume: a 5xx is retried before failing
with `REMOTE_FUNCTION_HTTP_RETRY_TIMEOUT ... after retrying 10 times`, while a 4xx fails
immediately with `REMOTE_FUNCTION_HTTP_FAILED_ERROR`. Both verified.

**Recommendation:** Route B is a legitimate option for a SQL-only audience against a
query-param API, and the governance story is real, since the connection controls the **host** as
well as the credential. Do not judge it on the Frankfurter case, which is a quirk of the demo
API rather than of the mechanism. For this build's FX ingestion, Route A stays the answer
because notebook 03 already fetches the whole window in one call.

---

### Which to use

| Situation | Use |
|---|---|
| One operator per API, reused across client canvases | **Route A** |
| Restricted to SQL, or you want UC to govern the host | Route B |
| Many sources per client, pagination, OAuth refresh, backoff | The notebook pipeline |

Designer API ingestion is real and worth demonstrating. But for the full workload, pagination
loops, retry with backoff and OAuth token refresh are still easier to write, test and version
in a notebook than inside an operator definition. The strong play is a **small number of Python
operators built once by engineering**, which the analytics team then reuses across every client by changing
config fields.

---

## What to demonstrate in the session

For the analytics team, in this order:

1. **Build Pipeline B from Prompt 2 using Genie Code.** Fastest way to show value.
2. **Break it deliberately.** Change a column name in the Select node, see the error, fix it.
3. **Add a column.** The single most common real request.
4. **Show the CTR trap.** Build it once by averaging `ctr_pct` and once from summed totals,
   and compare the numbers. This is the moment that teaches why the node order matters.
5. **Publish and schedule.** Show that the published file becomes a job like any other.

Skip Part 4 unless someone asks. It is a ceiling-of-capability answer, not a
day-one workflow.
