# Before the session

About ten minutes. The account signup is the one thing that cannot be rushed on the day, so
please do it ahead of time rather than in the first ten minutes of the session.

You will build everything yourself during the session, on your own workspace. That is why you
need an account of your own.

---

## 1. Create a Databricks Free Edition account

Free Edition is permanently free, covers everything these sessions use, and is a separate
account from any Databricks workspace you may already have access to at work.

1. Go to <https://login.databricks.com/signup>.
2. Choose **Free Edition**. Not the 14-day trial: it expires, and Free Edition does not.
3. Sign up and confirm you can log in and open a notebook.

**Do this even if you already use Databricks at work.** We will be creating catalogs, secrets
and jobs, which you may not have permission to do in a work workspace, and you should be free
to experiment without worrying about what you break.

---

## 2. Check you can run a notebook

Worth five minutes now, because it catches problems while there is still time to fix them.

1. Log into your Free Edition workspace.
2. **New > Notebook**.
3. Paste and run:

   ```python
   print(spark.sql("SELECT current_user(), current_date()").collect())
   ```

4. It should print your email address and today's date.

If the cell hangs for a minute or two on the first run, that is normal: serverless compute is
starting up. If it returns an error, send me the message before the session and we will sort it
out beforehand.

---

## 3. Reply with two things

A one-line answer to each is plenty:

1. **Have you used Databricks before?** Any exposure at all, or none. Both are fine.
2. **Would you like a 20 to 30 minute getting-started walkthrough at the start**, or would you
   rather go straight into building?

This decides whether I add an orientation segment at the front. There is no wrong answer, and
it is much easier to plan for than to improvise on the day.

---

## Checklist

- [ ] Free Edition account created, and I can log in
- [ ] Test notebook cell runs and prints my email and the date
- [ ] Replied with prior experience and walkthrough preference

---

## What you do *not* need

Nothing from your own environment is required, and nothing is blocked waiting on it:

- No access to your cloud provider, and no storage credentials.
- No real client data. The sessions use generated data for two fictional clients.
- No existing Databricks workspace or licence.
- Nothing installed on your laptop beyond a browser.

Everything is built from scratch in your own Free Edition workspace, using synthetic data, so
you can re-run all of it afterwards at your own pace.

---

## What to expect

Two sessions. The first builds the pipeline in Python: ingesting files and an API, then
transforming through bronze, silver and gold. The second operates it without writing code: row
level security, cost visibility, Genie, Lakeflow Designer and dashboards.

We build everything live. You will also get a completed copy of every notebook and guide, so if
you fall behind at any point you can pick up the finished version and keep going.
