# Ingesting from a connector: Google Drive, no code

**Audience:** anyone landing a source without writing a pipeline

Agenda item 2, the connector half. Notebook 02 lands CSVs into raw with Auto Loader, which is
the file-upload path. This guide covers the second path: a **ready-built connector** that pulls
files in on its own, using a personal Google Drive as the safe stand-in.

Google Drive is chosen deliberately for enablement: it needs no production credentials, just a
personal Google account, so it exercises the connector pattern without touching a live
customer source. The pattern is what transfers. In the real build the same idea is a native
Databricks connector (for example Salesforce or Google Analytics) or a managed connector (for a
source reached only through a third-party integration); the mechanics of authorising a connector
and pointing it at a destination are what you are practising here.

---

## Why a connector rather than the upload

Both end in the same place: a raw table that bronze reads. The difference is who does the moving.

| | CSV upload (notebook 02) | Connector (this guide) |
|---|---|---|
| Who moves the file | You, by hand or the CLI | The connector, on a schedule |
| Credentials | None | The source's, held once by the connector |
| Good for | A one-off, or a volume you already control | A live source you do not want to hand-maintain |
| Maintenance | A script per source | Configuration, no code |

This maps directly onto the customer's goal of replacing hand-maintained cloud integration jobs
with ready-built connectors. The upload path proves the medallion
pipeline; the connector path proves the ingestion pattern that reduces the integrations you
maintain.

---

## The shape: connector lands to a volume, Auto Loader picks it up

The cleanest pattern, and the one this guide uses, keeps the connector's only job as *getting the
file into the landing volume*. From there notebook 02 is unchanged: Auto Loader ingests whatever
lands, regardless of how it arrived.

```
Google Drive folder  ->  [connector / scheduled copy]  ->  /Volumes/.../landing/<client>/  ->  Auto Loader  ->  raw table
```

That separation is the point. Ingestion mechanism and transformation are decoupled, so swapping
Google Drive for a real connector later changes nothing downstream.

---

## Step 1: put the sample files in Google Drive

1. In your personal Google Drive, create a folder, for example `enablement_webinar`.
2. Upload the webinar CSVs from `data/landing/orbital_instruments/webinar__*.csv`.

Webinar is a good choice for the connector demo because it is the tactic the customer most wants
to bring in from an external provider, so the story lands: *this is how a webinar export would
arrive without anyone building an integration for it.*

---

## Step 2: authorise Databricks to read the Drive folder

There are two routes. Pick by how much setup you want on the day.

### Route A: the built-in Google Drive source (fastest for the session)

Lakeflow Designer and several ingestion surfaces list **Google Drive** as a source directly
([docs](https://docs.databricks.com/aws/en/designer/ingest-data)). This is the lowest-ceremony
path and the one to demo:

1. In the ingestion UI (Designer, or **+ New > Add data**), choose **Google Drive**.
2. Authorise with your personal Google account through the OAuth prompt. Databricks stores the
   token; you never paste a credential into a notebook.
3. Point it at the `enablement_webinar` folder.
4. Set the destination to the landing volume, `/Volumes/enablement/01_raw/landing/orbital_instruments/`,
   or read straight into a table.

### Route B: a scheduled copy into the volume

If the built-in source is not available on your workspace tier, a small job copies the files in.
This is still "no pipeline code": it is one file-copy step on a schedule, and Auto Loader does the
rest. See the Lakeflow Designer Python-operator pattern in the docs for how a connector-style copy
is wired without a full notebook.

Either way the credential lives **once**, in the connection or the OAuth grant, and never appears
in code that reads the data. That is the same governance win as UC connections and secret scopes:
one credential store, not one per script.

---

## Step 3: ingest what landed

Once the files are in `landing/orbital_instruments/`, run **notebook 02** with
`client_id = orbital_instruments`. Nothing about the notebook changes: it discovers the `webinar`
tactic from the filename and ingests it exactly as it does an uploaded file.

That is the proof: **how the bytes arrived does not reach the pipeline.** Upload, Google Drive,
or a native connector all converge on the same raw table.

---

## What this tells you about the real sources

The decision the POC actually has to make is **native connector versus managed connector**, per
source:

| Source | Likely path | Why |
|---|---|---|
| CRM (first-party connector exists) | Native Databricks connector | First-party connector exists |
| Web analytics (first-party connector exists) | Native Databricks connector | First-party connector exists |
| Source with no full API | Managed connector (via a third-party integration) | No full API; a managed connector is already onboarded |
| Other SaaS sources | Native or managed, confirm per source | Depends on connector availability |

The rule of thumb: **native connector where one exists, a managed connector where it does not,
upload only for a genuine one-off.** Google Drive here stands in for "a connector authorises once
and lands to a volume", which is true of all three.

The exact source list for the POC is the customer's to confirm. This guide proves the pattern so
that confirmation is the only open question, not the mechanics.

---

## What to demonstrate in the session

1. **Upload one file by hand** (notebook 02) so the raw table exists.
2. **Land the webinar files via Google Drive** using Route A, into the same volume.
3. **Re-run notebook 02** and show the webinar rows appear with no code change.
4. Name the real-source mapping above, and note that native-vs-managed-connector is the one
   decision the POC still needs from the customer.
