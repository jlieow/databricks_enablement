# Academic-literature retrieval with a Genie agent

**Audience:** anyone building a knowledge assistant over curated documents

Agenda item 9. The team wants to answer clinical questions by citing research literature. A Genie
agent over a volume of research abstracts provides grounded, cited answers without requiring a
separate knowledge-base platform or third-party API.

This is a **UI walkthrough and curation guide**. Notebook 10 provides a fallback API approach.
**Note:** The deprecated Knowledge Assistant is being phased out in favor of this Genie agent
pattern. Its availability in some regions is unconfirmed; check with the account team.

---

## Why curation matters for accuracy

Unlike a general search engine, a retrieval augmented generation (RAG) assistant is only as good as
its source documents. If the abstracts are vague, outdated, or biased toward one treatment, the
answers will inherit those flaws. Spending time on the document set before building the agent pays off.

---

## Step 1: curate and upload research abstracts

1. Choose a focused set of research papers relevant to the health authority's clinical focus.
   - Start with 10-30 abstracts. Too few gives limited grounding; too many dilutes relevance.
   - Aim for abstracts from the last 5 years. Clinical guidelines evolve.
   - Include abstracts from multiple viewpoints if relevant (different treatment approaches, etc.).

2. Save each abstract as a plain-text file, one per file. Example:
   - `Abstract_COPD_Exacerbation_Readmission.txt`
   - `Abstract_Hypertension_Management_Outpatient.txt`
   - `Abstract_Lab_Utilization_Optimization.txt`

3. Upload the files to `/Volumes/enablement/01_raw/research_abstracts/` in your workspace.

4. In the Databricks UI, go to **Catalog > enablement > 01_raw > Volumes > research_abstracts**
   and confirm the files are there.

---

## Step 2: create the Genie agent

1. **Genie** in the left nav, then **New**.
2. Title: `Health Research Advisor` or `Clinical Evidence Advisor`.
3. Warehouse: **Serverless Starter Warehouse**.
4. **Agent** mode (not "space" mode).
5. Add knowledge source:
   - Click **Add knowledge source**.
   - Select **Unity Catalog Volume**.
   - Navigate to `enablement.01_raw.research_abstracts`.
   - The agent will index the abstracts in the volume.

---

## Step 3: configure the agent

1. **Settings > System instructions.** Paste:

```
You are a clinical evidence assistant. Answer questions by citing the research abstracts
you have been given. Always provide:
1. A direct answer to the question.
2. The specific abstract(s) that support the answer, with title or key findings.
3. Any limitations or caveats from the literature (e.g., "based on studies of X population" or
   "effect size was small in this trial").

Never make up evidence. If no abstract addresses the question, say so explicitly.
Never contradict the abstracts. If abstracts disagree, present both views and note the conflict.
```

2. **Settings > Citation mode:** Turn on **Full citations**. This forces the agent to cite every
   claim back to a source abstract.

---

## Step 4: benchmark before use

Ask a few test questions to verify accuracy:

- "What interventions reduce hospital readmissions for patients with congestive heart failure?"
  - Expect an answer citing specific abstracts by title or key finding.
  - If no answer, check that the abstracts actually contain relevant research.

- "What is the latest guidance on outpatient lab ordering?"
  - Expect caveats like "based on [year] research" or "effect sizes varied."
  - If the answer is vague, the abstracts may be too general.

- "Does this drug work for this condition?" (Pick a specific combination not in the abstracts.)
  - Expect an explicit "not addressed in the abstracts I have" or "no evidence in my sources."
  - If the agent makes something up, reconfigure the system instructions or add more specific abstracts.

---

## Step 5: iteration and maintenance

- **Add abstracts over time.** As guidelines evolve or new evidence emerges, upload new abstracts
  and the agent picks them up automatically.
- **Remove outdated abstracts.** Delete files from the volume if they are superseded or known to be
  flawed. The agent will stop citing them.
- **Monitor accuracy.** Have domain experts review a sample of answers monthly. If accuracy drifts,
  review the abstracts for bias or staleness.

---

## Key differences from Knowledge Assistant

- **Volume-based, not managed knowledge-base.** You own and version-control the abstracts in Git or
  as managed files in Unity Catalog.
- **Curation is explicit.** You choose the abstracts; they do not come from a black-box index.
- **Citations are enforced.** Every claim the agent makes is traceable to a source you control.
- **Accuracy is your responsibility.** If the abstracts are wrong, the agent will confidently repeat
  the error. The old Knowledge Assistant delegated curation to an external service.

