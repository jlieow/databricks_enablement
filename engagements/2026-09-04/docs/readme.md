# Enablement materials for health analytics

Completed notebooks and guides from the enablement session. We build these live and from scratch;
these copies are here so you can catch up if you fall behind, and to refer back to afterwards.

Everything runs on **Databricks Free Edition**, so you can run all of it on your own account, even
though the real POC build happens on the customer's cloud workspace.

## Start here

**[`../AGENDA.md`](../AGENDA.md)** maps every agenda item to its file(s), and covers setup, running
order and the gotchas worth knowing. Read that first.

## What is in this folder

| Guide | For | Files |
|---|---|---|
| [`../../../shared/prework.md`](../../../shared/prework.md) | Everyone, before the session. About ten minutes | Shared across engagements |
| `genie_space_guide.md` | Agenda item 10: building the Genie space in the UI over the consolidated gold table | Genie curation discipline |
| `asset_bundles_guide.md` | Agenda item 5: packaging pipelines, models, and apps as Databricks Asset Bundles for repeatable deployment | Develop-here / deploy-into-client pattern |
| `academic_rag_guide.md` | Agenda item 9: building a Genie agent over curated research abstracts; RAG accuracy and document quality | Retrieval augmented generation |
| `ai_gateway_guide.md` | Agenda item 11: routing large language model calls through the Databricks AI gateway for governance, rate limits, failover, and guardrails | LLM governance and cost control |

Notebooks are in `../notebooks/`, seed data and the dashboard file in `../data/`.

## The scenario

The team is building an end-to-end health analytics platform natively on Databricks for two fictional
health districts: data capture, classical risk-stratification model training, clinical-note extraction,
academic-literature retrieval, batch serving to PostgreSQL, dashboards, and a Databricks App. Enablement
mirrors that on safe synthetic data: patient encounter records across three clinical data streams
(outpatient visits, inpatient admissions, lab results) for two fictional districts, consolidated through
Bronze, Silver, Gold into clinical analytics tables. Four AI workstreams demonstrated: classical risk
model (scikit-learn on CPU), clinical-note extraction (AI functions), academic-literature retrieval (Genie
agent), and dashboard summaries (AI functions). All batch-served and packaged for repeatable deployment.

No live sources and no production credentials. The connector story is deferred to the build. The real
customer's large language model endpoints, PostgreSQL connectivity, and model accuracy tuning all come
in at the build, not here. Clinical data is synthetic; clinical notes are synthetic; research abstracts
are synthetic and fictional. Nothing real or identifying appears in this material.

