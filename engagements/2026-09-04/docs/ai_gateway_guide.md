# Unity AI Gateway: LLM governance and cost control

**Audience:** whoever manages large language model (LLM) access and spend for the team

Agenda item 11. The team is calling multiple large language models for clinical-note extraction,
dashboard summaries, and the Genie agent. The Databricks AI Gateway centralizes and governs all
those calls in one place, giving rate limits, budget controls, automatic failover between models,
and guardrail policies.

This is a **reference pattern and UI walkthrough**, not a required hands-on build. The real gateway
configuration and guard rails happen during the full build with the customer's production models.
**Note:** The AI Gateway is region-gated and not fully available on Free Edition in all regions.

---

## Why a gateway

Without a gateway, the team calls models directly:
- Multiple services, multiple APIs, multiple authentication methods.
- No visibility into who is using which model or how much it costs.
- No ability to swap models (e.g., if one vendor is slow, pick another) without code changes.
- No rate limits; a runaway pipeline could incur unlimited spend.

With a gateway:
- One API, one authentication, one place to manage spend.
- Route all calls through the gateway; swap models by changing config, not code.
- See usage per model, per user, per job.
- Rate limits and budget caps prevent surprises.
- Guardrail policies (e.g., "do not respond to requests about real patient names") are enforced
  centrally.

---

## Setting up the gateway

1. **Admin console > AI Gateway** (if available in your region).
2. **Create a gateway endpoint** for each model:
   - Name: `health-llm-clinical-extraction`
   - Model: your chosen large language model (e.g., GPT-4, Mixtral, etc.)
   - Rate limit: e.g., 100 requests per minute
   - Budget cap: e.g., USD 1000 per month
3. **Add models in failover order:**
   - Primary: your preferred model
   - Secondary: a cheaper fallback (e.g., if the primary is overloaded, use a smaller model)
   - Tertiary: another fallback
4. The gateway tries the primary first; if it fails or is rate-limited, it moves to the secondary.

---

## Calling the gateway from code

Instead of calling a model directly:

```python
# Without gateway (direct)
import anthropic
client = anthropic.Anthropic(api_key="your-api-key")
response = client.messages.create(
    model="claude-3-sonnet",
    messages=[{"role": "user", "content": "Extract: ..."}]
)

# With gateway (from within Databricks)
response = spark.ai.extract(
    "Extract structured fields from this clinical note: ...",
    gateway="health-llm-clinical-extraction"
)
```

The gateway intercepts the call, increments usage counters, applies guardrails, and routes to the
appropriate model. If rate limits are hit, it returns a clear error instead of a surprise invoice.

---

## Guardrails: the policy layer

Common guardrails:

- **Input filtering:** Block requests that mention real patient names or medical record numbers.
- **Output filtering:** Block responses that suggest a diagnosis or treatment without a clinical
  disclaimer.
- **Logging:** Log all calls for audit and compliance.
- **Timeouts:** Fail explicitly if a model takes too long instead of hanging.

Example policy (pseudocode):

```yaml
guardrails:
  input:
    - block if matches regex: \b\d{6,}\b  # Likely MRN
    - block if contains: real patient names
  output:
    - require disclaimer if suggests_diagnosis: true
    - log all interactions to compliance_audit table
  rate_limits:
    per_user: 100 req/min
    per_job: 500 req/hour
  budget:
    monthly_cap: 5000
    alert_threshold: 75%
```

---

## Monitoring and troubleshooting

- **Usage dashboard:** The AI Gateway admin console shows usage per model, user, job, and time period.
- **Cost tracking:** Total spend against budget, so you see cost trending before it becomes a problem.
- **Failover logs:** See which models were attempted and why (timeout, rate limit, error, etc.).
- **Alerting:** Set up alerts when usage or cost crosses thresholds.

---

## Integration with the health solution

For the health analytics platform:

1. Create gateway endpoints for:
   - Clinical-note extraction (strict guardrails, output filtered for medical accuracy)
   - Dashboard summarization (looser guardrails, just logging)
   - Genie agent (moderate guardrails, cites sources)

2. Route all LLM calls through the gateway:
   - Notebook 05 (clinical extraction) calls `gateway: clinical-note-extraction`
   - Notebook 12 (dashboard summaries) calls `gateway: health-summaries`
   - Genie agent over gold calls `gateway: health-genie`

3. Monitor spend and accuracy:
   - Monthly review of usage per endpoint
   - Quarterly review of guardrail violations and model accuracy

This centralizes control and makes it easy to add models, swap vendors, or adjust budgets without
touching application code.

