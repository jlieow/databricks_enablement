# Enablement materials

Completed notebooks and guides from the enablement session. We build these live and from scratch;
these copies are here so you can catch up if you fall behind, and to refer back to afterwards.

Everything runs on **Databricks Free Edition**, so you can run all of it on your own account, even
though the real POC build happens on the customer's cloud workspace.

## Start here

**[`../AGENDA.md`](../AGENDA.md)** maps every agenda item to its file, and covers setup, running
order and the gotchas worth knowing. Read that first.

## What is in this folder

| Guide | For |
|---|---|
| [`../../../shared/prework.md`](../../../shared/prework.md) | Everyone, before the session. About ten minutes. Shared across engagements |
| `google_drive_connector_guide.md` | Agenda item 2: the connector half. Landing a source with no code, via Google Drive as a safe stand-in |
| `genie_space_guide.md` | Agenda item 4: building the Genie space in the UI, and benchmarking its answers |
| `power_bi_connection_guide.md` | Buffer / nice-to-have: connecting Power BI directly to Databricks |

Notebooks are in `../notebooks/`, seed data and the dashboard file in `../data/`.

## The scenario

The customer is a scientific publisher that runs marketing campaigns for manufacturer clients and
reports the results back to them. Enablement mirrors that on safe sample data: campaign engagement
across three **tactics** (product listings, email blasts, webinars) for two fictional clients,
consolidated through Bronze → Silver → Gold into one internal report per client, then surfaced on an
AI/BI dashboard with a Genie space over it, with a cost readout and a governance foundation.

No live sources and no production credentials are used. The connector story is carried by a personal
Google Drive; the real native-connector-versus-managed-connector decision is confirmed at the build,
not here.
