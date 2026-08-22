# Building the Genie space by hand

**Audience:** whoever curates a space per client

Notebook 05 creates a working space via the API. This guide is for building one in the UI, which
is what the team will actually do for each new client. Building it by hand is also better
enablement: the curation is the work, and doing it manually is what makes that obvious.

This is agenda item 4, the Genie half. It is also the closest internal-facing taste of a planned
client-facing AI experience, so the accuracy discipline here is the discipline that product will
need.

---

## Why curation is the whole job

A Genie space with no instructions will answer questions. It will also, confidently, answer some
of them wrongly. The failure mode is not "I do not know", it is a plausible number that is subtly
incorrect, which is far more dangerous in a client-facing context.

The error this dataset most invites:

**Averaging a rate.** Asked for "overall engagement rate", the naive answer is
`AVG(engagement_rate_pct)`. That weights a campaign with 200 impressions equally with one with
200,000. The correct answer is `SUM(engagements)/SUM(impressions)*100`. The same trap applies to
lead rate.

It looks reasonable in a chat window. Everything below exists to prevent it.

---

## Step 1: comment the tables first

Do this before creating the space. Genie reads Unity Catalog comments, and this single step does
more for accuracy than any instruction text. It is also the semantic layer the customer says it
lacks today: the comments live on the table, so they serve Catalog Explorer, Genie, and anyone
browsing, all at once.

In **Catalog Explorer**, open the gold table and add a table comment plus a comment on every
column. Or run the SQL from notebook 05, which does the same thing.

The test of a good column comment: would a new analyst know what to do with this column without
asking anyone? For example, `engagements` should say it counts clicks, opens, or webinar
attendance and is always at most `impressions`, not merely "engagements".

---

## Step 2: create the space

1. **Genie** in the left nav, then **New**.
2. Title: `Campaign Engagement - <client_id>`.
3. Warehouse: **Serverless Starter Warehouse** (the only one on Free Edition).
4. Add tables:
   - `enablement.04_gold.gold_<client>_master` — the primary table.
   - `enablement.03_silver.silver_<client>_engagement` — for data quality questions only.

Adding the silver table is a deliberate choice. Without it, "how many rows were rejected?" cannot
be answered at all. With it, Genie needs telling when to use which, hence the instruction below.

---

## Step 3: instructions

**Settings > Instructions.** Paste the following. Each line prevents a specific wrong answer
rather than being general advice.

```
Never average engagement_rate_pct or lead_rate_pct directly across rows. Recalculate from the
underlying totals: engagement rate is SUM(engagements)/SUM(impressions)*100 and lead rate is
SUM(leads)/SUM(engagements)*100. Averaging per-row ratios weights a tiny campaign the same as a
large one.

report_date is the date the campaign activity happened. It is not the date the data was loaded.
Always filter and group on report_date for time based questions.

Leads for recent dates may still be restated for up to 30 days. When a user asks about the last
few days, mention that figures may change.

campaign_id is only unique within a tactic. When counting distinct campaigns across tactics,
group by both tactic and campaign_id.

The gold master table contains only rows that passed data quality validation. If a user asks
about rejected, flagged or missing data, use the silver table where dq_status = 'flagged' and
dq_flags lists the reasons.

'Performance' in this context means efficiency: engagement rate and lead rate. It does not mean
volume (impressions or leads). If a user asks which campaign performed best, ask whether they
mean the most efficient or the largest, unless it is clear from context.
```

That last one matters more than it looks. "Which campaign performed best" is genuinely ambiguous,
and reporting it the wrong way back to a client is a bad moment. Teaching Genie to ask rather than
guess is better than teaching it to pick.

---

## Step 4: named measures

**Settings > SQL snippets > Measures.** These make the correct calculation the default.

| Alias | SQL | Display name | Synonyms |
|---|---|---|---|
| `total_impressions` | `SUM(impressions)` | Total Impressions | impressions, reach, views |
| `total_leads` | `SUM(leads)` | Total Leads | leads, conversions, signups |
| `engagement_rate` | `SUM(engagements) * 100.0 / NULLIF(SUM(impressions), 0)` | Engagement Rate % | engagement rate, engagement |
| `lead_rate` | `SUM(leads) * 100.0 / NULLIF(SUM(engagements), 0)` | Lead Rate % | lead rate, conversion rate |

Note `NULLIF` throughout. Without it, a campaign with zero engagements produces a divide-by-zero
that either errors or returns infinity, and one infinity poisons every aggregate above it.

The synonyms matter because people do not use column names. Somebody will ask about "conversion
rate", nobody will ask about `lead_rate` as spelled in the measure.

Note that `engagement_rate` and `lead_rate` are **measures, not columns**: the gold table stores
`impressions`, `engagements` and `leads`, and the measure is what combines them correctly.
Defining them here is what stops Genie inventing its own version.

---

## Step 5: worked examples

**Settings > Example queries.** Instructions describe; examples demonstrate. Add at least these
two, because they cover the trap and the volume floor.

**"Which campaign had the best engagement rate?"**
```sql
SELECT campaign_name, tactic,
       SUM(impressions) AS impressions,
       SUM(engagements) AS engagements,
       ROUND(SUM(engagements) * 100.0 / NULLIF(SUM(impressions), 0), 3) AS engagement_rate_pct
FROM enablement.04_gold.gold_helix_biosciences_master
GROUP BY campaign_name, tactic
HAVING SUM(impressions) > 1000
ORDER BY engagement_rate_pct DESC
```

The `HAVING` clause is the interesting part. Without a volume floor, a campaign with 3 impressions
and 1 engagement tops the table at 33 percent. Every efficiency ranking needs a minimum threshold,
and showing Genie one example teaches it the habit.

**"What were total leads by tactic last week?"**
```sql
SELECT tactic,
       SUM(leads) AS leads,
       SUM(impressions) AS impressions,
       SUM(engagements) AS engagements
FROM enablement.04_gold.gold_helix_biosciences_master
WHERE report_date >= DATE_SUB(
        (SELECT MAX(report_date) FROM enablement.04_gold.gold_helix_biosciences_master), 7)
GROUP BY tactic
ORDER BY leads DESC
```

Anchoring on `MAX(report_date)` rather than `CURRENT_DATE()` is deliberate: sample data is rarely
from today, and "last week" relative to now would return nothing.

---

## Step 6: starter questions

**Settings > Sample questions.** These appear as clickable prompts and set expectations about
what the space is for.

```
What were total leads by tactic last week?
Which campaign had the best engagement rate?
Show me daily impressions and engagements for the last 14 days
Which tactic generates the most leads?
Are there any days where engagement dropped to zero?
What is the lead rate by campaign?
```

---

## Step 7: benchmark it

This is the step that gets skipped, and it is the one that matters most: Genie answering
**accurately**, not Genie answering.

Run the SQL, note the answer, then ask Genie the question and compare.

| Ask Genie | Correct answer from |
|---|---|
| What were total leads? | `SELECT SUM(leads) FROM <gold>` |
| How many campaigns are there? | `SELECT COUNT(DISTINCT campaign_id) FROM <gold>` |
| Which tactic had the most leads? | `GROUP BY tactic ORDER BY SUM(leads) DESC LIMIT 1` |
| **What is the overall engagement rate?** | `SELECT SUM(engagements)*100.0/NULLIF(SUM(impressions),0) FROM <gold>` |
| **What is the overall lead rate?** | `SELECT SUM(leads)*100.0/NULLIF(SUM(engagements),0) FROM <gold>` |
| What was the busiest day by impressions? | `GROUP BY report_date ORDER BY SUM(impressions) DESC LIMIT 1` |

Notebook 05 prints this table with the answers already computed for the current data.

**The two bold rows are the test.** If Genie returns the averaged figure rather than the recomputed
one, the measures are not being picked up. Strengthen the instruction, add another example, and ask
again. Demonstrating that loop live is more valuable than a space that happens to work first time,
because it shows the team how to fix it themselves.

---

## Security

A row filter applies to Genie exactly as it does to a dashboard, because enforcement is in Unity
Catalog rather than in the query. A user asking "show me all clients" gets only the clients they
are entitled to, and there is nothing to configure in Genie for that to be true.

**Note which table you point the space at.** The space built here reads `gold_<client>_master`,
which is one client per table and carries **no** row filter, so separation comes from table grants
instead. The filter from notebook 07 is on `gold_all_clients_master_filtered`. Point a space at
that table and the filter does the work, which is the one-space-for-all-clients option below and
the pattern the client-facing product will use.

---

## Maintaining it per client

For each new client, the space needs repointing at that client's tables. The efficient path:

1. Duplicate the existing space.
2. Swap the two table references to the new client.
3. Update the title.

Instructions, measures and examples carry over unchanged, because they describe the shape of the
data rather than a specific client. That is the same "build once, reconfigure per client" argument
as the pipeline template in notebook 04.

An alternative worth considering for production: point one space at
`gold_all_clients_master_filtered` and rely on the row filter for separation. One space to maintain
instead of one per client, with entitlements doing the work. The trade-off is that a user with
access to several clients can compare across them, which may or may not be desirable, and for a
client-facing space is exactly what you must prevent.
