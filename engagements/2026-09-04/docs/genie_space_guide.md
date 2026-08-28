# Building the Genie space by hand

**Audience:** whoever builds and curates a Genie space per district

Notebook 11 creates a working space via the API. This guide is for building one in the UI, which
is what the team will actually do for each new district. Building it by hand is also better
enablement: the curation is the work, and doing it manually is what makes that obvious.

This is agenda item 10, the Genie half over the consolidated gold table. It demonstrates the same
accuracy discipline that a client-facing analytics interface will need.

---

## Why curation is the whole job

A Genie space with no instructions will answer questions. It will also, confidently, answer some of
them wrongly. The failure mode is not "I do not know", it is a plausible number that is subtly
incorrect, which is far more dangerous in a clinical-analytics or client-facing context.

The error this dataset most invites:

**Averaging a rate when you should sum and recalculate.** Asked for "overall readmission rate across
districts", the naive answer is `AVG(readmission_rate_pct)`. That weights a small district equally
with a large one. The correct answer is `SUM(readmission_count)/SUM(total_encounters)*100`. The same
trap applies to abnormal lab result rate.

It looks reasonable in a chat window. Everything below exists to prevent it.

---

## Step 1: comment the tables first

Do this before creating the space. Genie reads Unity Catalog comments, and this single step does
more for accuracy than any instruction text. It is also the semantic layer the team says it lacks
today: the comments live on the table, so they serve Catalog Explorer, Genie, and anyone browsing.

In **Catalog Explorer**, open the gold table (`enablement.04_gold.gold_all_districts_master`) and add
a table comment plus a comment on every column. Or run the SQL from notebook 11, which does the same.

The test of a good column comment: would a new analyst know what to do with this column without asking?
For example, `readmission_count` should say it is the count of hospital readmissions within 30 days
and must be checked against `total_encounters` (it should never exceed it), not merely "readmissions".

---

## Step 2: create the space

1. **Genie** in the left nav, then **New**.
2. Title: `District Health Analytics - <district_name>` or `All Districts`.
3. Warehouse: **Serverless Starter Warehouse** (the only one on Free Edition).
4. Add tables:
   - `enablement.04_gold.gold_all_districts_master` — the primary table.
   - `enablement.03_silver.silver_<district>_encounters` — for data quality questions only (optional).

---

## Step 3: instructions

**Settings > Instructions.** Paste the following. Each line prevents a specific wrong answer.

```
Never average readmission_rate_pct or abnormal_lab_rate_pct directly across rows. Recalculate from
the underlying totals: readmission rate is SUM(readmission_count)/SUM(total_encounters)*100 and
abnormal lab rate is SUM(abnormal_result_count)/SUM(total_results)*100. Averaging per-row rates
weights a small district equally with a large one.

visit_date is the date the encounter happened. It is not the date the data was loaded.
Always filter and group on visit_date for time-based questions.

Encounter counts and patient counts may be revised for up to 7 days as follow-up information is
received. When a user asks about the last few days, mention that figures may change.

district_id uniquely identifies a health district. When comparing districts, always filter or group
by district_id explicitly.

The gold master table contains only rows that passed data quality validation. If a user asks about
rejected, flagged or missing data, use the silver table where dq_status = 'flagged' and dq_flags
lists the reasons.

'Performance' in a clinical context usually means efficiency or outcome rate (readmission rate,
abnormal lab rate, average length of stay). It does not mean volume (total encounters). If a user
asks which district performed best, ask whether they mean most efficient or largest, unless clear
from context.
```

---

## Step 4: named measures

**Settings > SQL snippets > Measures.** These make the correct calculation the default.

```
Readmission Rate:
  SUM(readmission_count) / SUM(total_encounters) * 100

Abnormal Lab Rate:
  SUM(abnormal_result_count) / SUM(total_results) * 100

Average Length of Stay:
  SUM(total_inpatient_days) / SUM(inpatient_encounters)

Outpatient Visit Rate (per patient):
  SUM(outpatient_encounters) / COUNT(DISTINCT patient_id)
```

---

## Step 5: benchmark

Test a few questions before handing it over:

- "What is the readmission rate across all districts?" (Should use SUM/SUM, not AVG.)
- "How many encounters in northmoor district last week?" (Should filter by district_id and visit_date.)
- "How many of those had abnormal lab results?" (Should use the abnormal_result_count column.)

If any answer is wrong, check the instructions and the column comments again.

