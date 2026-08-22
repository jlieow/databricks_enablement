# Building the Genie space by hand

**Audience:** analytics team

Notebook 08 creates a working space via the API. This guide is for building one in the UI,
which is what the team will actually do for each new client. Building it by hand is also
better enablement: the curation is the work, and doing it manually is what makes that
obvious.

---

## Why curation is the whole job

A Genie space with no instructions will answer questions. It will also, confidently, answer
some of them wrongly. The failure mode is not "I do not know", it is a plausible number
that is subtly incorrect, which is far more dangerous in a client-facing context.

The two errors this dataset invites:

1. **Averaging a ratio.** Asked for "overall CTR", the naive answer is `AVG(ctr_pct)`. That
   weights a campaign with 200 impressions equally with one with 200,000. The correct answer
   is `SUM(clicks)/SUM(impressions)`.
2. **Summing mixed currencies.** `SUM(spend_local)` adds pounds to euros and produces a
   number that means nothing.

Both look reasonable in a chat window. Everything below exists to prevent them.

---

## Step 1: comment the tables first

Do this before creating the space. Genie reads Unity Catalog comments, and this single step
does more for accuracy than any instruction text.

In **Catalog Explorer**, open the gold table and add a table comment plus a comment on every
column. Or run the SQL from notebook 08, which does the same thing.

The test of a good column comment: would a new analyst know what to do with this column
without asking anyone? For example, `spend_usd` should say it is converted for cross-client
comparison, not merely "spend in USD", because the comparison purpose is what stops someone
using `spend_local` by mistake.

---

## Step 2: create the space

1. **Genie** in the left nav, then **New**.
2. Title: `Client Performance - <client_id>`.
3. Warehouse: **Serverless Starter Warehouse** (the only one on Free Edition).
4. Add tables:
   - `enablement.04_gold.gold_<client>_master` — the primary table.
   - `enablement.03_silver.silver_<client>_performance` — for data quality questions only.

Adding the silver table is a deliberate choice. Without it, "how many rows were rejected?"
cannot be answered at all. With it, Genie needs telling when to use which, hence the
instruction below.

---

## Step 3: instructions

**Settings > Instructions.** Paste the following. Each line prevents a specific wrong
answer rather than being general advice.

```
When comparing or totalling spend across clients or currencies, always use spend_usd.
Only use spend_local when the user explicitly asks about a single client's billing currency.

Never average ctr_pct directly across rows. Recalculate from the underlying totals:
CTR is SUM(clicks)/SUM(impressions)*100 and CPA is SUM(spend_usd)/SUM(conversions). Averaging
per-row ratios weights a tiny campaign the same as a large one.

report_date is the date the advertising activity happened. It is not the date the data was
loaded. Always filter and group on report_date for time based questions.

Conversions and spend for recent dates may still be restated by the ad platforms for up to
30 days. When a user asks about the last few days, mention that figures may change.

campaign_id is only unique within a platform. When counting distinct campaigns across
platforms, group by both platform and campaign_id.

The gold master table contains only rows that passed data quality validation. If a user
asks about rejected, flagged or missing data, use the silver table where dq_status =
'flagged' and dq_flags lists the reasons.

'Performance' in this context means efficiency metrics: CTR, CPA and conversion rate. It
does not mean spend volume. If a user asks which campaign performed best, ask whether they
mean the most efficient or the largest, unless it is clear from context.
```

That last one matters more than it looks. "Which campaign performed best" is genuinely
ambiguous, and an agency answering it the wrong way in front of a client is a bad moment.
Teaching Genie to ask rather than guess is better than teaching it to pick.

---

## Step 4: named measures

**Settings > SQL snippets > Measures.** These make the correct calculation the default.

| Alias | SQL | Display name | Synonyms |
|---|---|---|---|
| `total_spend_usd` | `SUM(spend_usd)` | Total Spend (USD) | spend, cost, media spend, investment |
| `ctr` | `SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0)` | Click-Through Rate % | ctr, click through rate, click rate |
| `cpa` | `SUM(spend_usd) / NULLIF(SUM(conversions), 0)` | Cost Per Acquisition (USD) | cpa, cost per acquisition, cost per conversion |
| `cvr` | `SUM(conversions) * 100.0 / NULLIF(SUM(clicks), 0)` | Conversion Rate % | cvr, conversion rate |
| `cpm` | `SUM(spend_usd) * 1000.0 / NULLIF(SUM(impressions), 0)` | Cost Per Mille (USD) | cpm, cost per thousand impressions |

Note `NULLIF` throughout. Without it, a campaign with zero conversions produces a
divide-by-zero that either errors or returns infinity, and one infinity poisons every
aggregate above it.

The synonyms matter because people do not use column names. Somebody will ask about
"cost per acquisition", nobody will ask about `cpa` as spelled in the measure.

Note that `cpa` and `cpm` are **measures, not columns**: the gold table stores `spend_usd`,
`conversions` and `impressions`, and the measure is what combines them correctly. Defining them
here is what stops Genie inventing its own version.

---

## Step 5: worked examples

**Settings > Example queries.** Instructions describe; examples demonstrate. Add at least
these two, because they are the traps.

**"Which campaign had the best click-through rate?"**
```sql
SELECT campaign_name, platform,
       SUM(impressions) AS impressions,
       SUM(clicks) AS clicks,
       ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 3) AS ctr_pct
FROM enablement.04_gold.gold_northwind_retail_master
GROUP BY campaign_name, platform
HAVING SUM(impressions) > 1000
ORDER BY ctr_pct DESC
```

The `HAVING` clause is the interesting part. Without a volume floor, a campaign with 3
impressions and 1 click tops the table at 33 percent. Every efficiency ranking needs a
minimum threshold, and showing Genie one example teaches it the habit.

**"What was total spend by platform last week?"**
```sql
SELECT platform,
       ROUND(SUM(spend_usd), 2) AS spend_usd,
       SUM(impressions) AS impressions,
       SUM(clicks) AS clicks
FROM enablement.04_gold.gold_northwind_retail_master
WHERE report_date >= DATE_SUB(
        (SELECT MAX(report_date) FROM enablement.04_gold.gold_northwind_retail_master), 7)
GROUP BY platform
ORDER BY spend_usd DESC
```

Anchoring on `MAX(report_date)` rather than `CURRENT_DATE()` is deliberate: sample data is
rarely from today, and "last week" relative to now would return nothing.

---

## Step 6: starter questions

**Settings > Sample questions.** These appear as clickable prompts and set expectations
about what the space is for.

```
What was total spend by platform last week?
Which campaign had the lowest cost per acquisition?
Show me daily impressions and clicks for the last 14 days
Which platform has the best click-through rate?
Are there any days where spend dropped to zero?
What is the conversion rate by campaign?
```

---

## Step 7: benchmark it

This is the step that gets skipped, and it is the one that matters most:
Genie answering **accurately**, not Genie answering.

Run the SQL, note the answer, then ask Genie the question and compare.

| Ask Genie | Correct answer from |
|---|---|
| What was total spend in USD? | `SELECT ROUND(SUM(spend_usd),2) FROM <gold>` |
| How many campaigns are there? | `SELECT COUNT(DISTINCT campaign_id) FROM <gold>` |
| Which platform had the highest spend? | `GROUP BY platform ORDER BY SUM(spend_usd) DESC LIMIT 1` |
| **What is the overall click-through rate?** | `SELECT SUM(clicks)*100.0/NULLIF(SUM(impressions),0) FROM <gold>` |
| **What is the average CPA?** | `SELECT SUM(spend_usd)/NULLIF(SUM(conversions),0) FROM <gold>` |
| What was the busiest day by impressions? | `GROUP BY report_date ORDER BY SUM(impressions) DESC LIMIT 1` |

Notebook 08 prints this table with the answers already computed for the current data.

**The two bold rows are the test.** If Genie returns the averaged figure rather than the
recomputed one, the measures are not being picked up. Strengthen the instruction, add
another example, and ask again. Demonstrating that loop live is more valuable than a space
that happens to work first time, because it shows the team how to fix it themselves.

---

## Security

A row filter applies to Genie exactly as it does to a dashboard, because enforcement is in Unity
Catalog rather than in the query. A user asking "show me all clients" gets only the clients they
are entitled to, and there is nothing to configure in Genie for that to be true.

**Note which table you point the space at.** The space built here reads
`gold_<client>_master`, which is one client per table and carries **no** row filter, so
separation comes from table grants instead. The filter from notebook 06 is on
`gold_all_clients_master_filtered`. Point a space at that table and the filter does the work,
which is the one-space-for-all-clients option below.

---

## Maintaining it per client

For each new client, the space needs repointing at that client's tables. The efficient path:

1. Duplicate the existing space.
2. Swap the two table references to the new client.
3. Update the title.

Instructions, measures and examples carry over unchanged, because they describe the shape of
the data rather than a specific client. That is the same "build once, reconfigure per
client" argument as the pipeline template.

An alternative worth considering for production: point one space at
`gold_all_clients_master_filtered` and rely on the row filter for separation. One space to maintain
instead of 50, with entitlements doing the work. The trade-off is that a user with access to
several clients can compare across them, which may or may not be desirable.
