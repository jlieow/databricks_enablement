# Connecting Power BI to Databricks

**Audience:** the analytics team

Buffer / nice-to-have. The customer already uses Power BI, so this is the alternative
consumption path to compare against the AI/BI dashboard. It is not a core POC deliverable, but it
is a common question and quick to show, so it belongs in the Tuesday buffer.

The one thing worth internalising: **connecting Power BI does not move or copy the data.** Power BI
queries the gold table live over the SQL warehouse, so the medallion pipeline, the metric
definitions, and the Unity Catalog governance all still apply. Power BI is a viewer, not a second
copy of the truth.

---

## Which connection mode, and why it matters for governance

| Mode | What it does | Use when |
|---|---|---|
| **DirectQuery** (recommended) | Every visual queries Databricks live | You want UC row filters and masks enforced, and always-current data |
| **Import** | Pulls a copy into the Power BI model | You need offline speed and accept a stale, ungoverned copy |

**Prefer DirectQuery for anything client-related.** The row filter from notebook 07 is enforced by
Unity Catalog on the query, so with DirectQuery a Power BI user sees only the clients they are
entitled to, for free. Import pulls a snapshot into the `.pbix` file, which leaves Unity Catalog's
enforcement behind: the copy is only as governed as the file. For the customer's per-client
isolation requirement, that distinction is the whole point.

---

## Step 1: get the connection details

From the Databricks workspace:

1. **SQL Warehouses**, open the warehouse (Serverless Starter Warehouse on Free Edition).
2. **Connection details** tab.
3. Copy **Server hostname** and **HTTP path**.

There is also a **Partner Connect** shortcut: **Partner Connect > Power BI** downloads a `.pbids`
file with these fields pre-filled, which is the fastest route and worth showing.

---

## Step 2: connect from Power BI Desktop

1. **Get Data > Azure Databricks** (or **More > Database > Azure Databricks**).
2. Paste the **Server hostname** and **HTTP path**.
3. Data Connectivity mode: **DirectQuery**.
4. Sign in. On a workspace backed by **Microsoft Entra ID (Azure AD)** the viewer authenticates as
   themselves, which is what makes per-user row filtering work. A personal
   access token also works but ties every query to one identity, so avoid it for governed data.
5. In the Navigator, browse `enablement > 04_gold` and pick `gold_all_clients_master_filtered`.

Choosing the **filtered** table over the unfiltered one is the same lesson as everywhere else in
this build: let Unity Catalog do the filtering, do not rebuild it in the BI tool.

---

## Step 3: confirm governance carried through

The test that this is really governed and not just connected:

1. Query `gold_all_clients_master_filtered` from Power BI as a user entitled to one client.
2. Confirm only that client's rows appear, with no filter set in Power BI itself.

If both clients show, the connection is reading the unfiltered table, or authenticating as a
service identity in the `admins` escape hatch. That is the first thing to check, and it mirrors
the notebook 07 warning about `embed_credentials`.

---

## When to use which consumption path

| Path | Best for |
|---|---|
| AI/BI dashboard | The internal report itself, and natural-language follow-ups via Genie, all inside Databricks |
| Power BI (DirectQuery) | Fitting Databricks into existing Power BI workflows and report distribution |
| Genie | Ad-hoc questions without building a visual |

All three read the **same gold table** with the **same metric definitions and the same row filter**.
That is the payoff of computing the metrics once in gold: the tool is a choice of surface, not a
place where the numbers can diverge.
