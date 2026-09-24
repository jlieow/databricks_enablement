#!/usr/bin/env bash
#
# Run the app on your laptop with uv, using the LOCAL values from local.env.
#
# One command does everything:
#   --with-requirements requirements.txt  installs the deps into an ephemeral env
#   --env-file local.env                  loads local.env's KEY=value into the env
#   python app.py                         runs the app (the same command the
#                                         Databricks Apps platform runs)
#
# So there is no venv to manage, no shell `source`, and app.py stays identical
# to what deploys - it just reads os.environ, and uv is what puts local.env's
# values there for a local run.
#
# This script and local.env both live in src/app, but are excluded from the
# bundle sync (config/sync.yml), so neither is ever uploaded as app code.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it (e.g. 'brew install uv') - https://docs.astral.sh/uv/" >&2
  exit 1
fi

echo "Running locally on http://localhost:${DATABRICKS_APP_PORT:-8000}  (Ctrl-C to stop)"
exec uv run --env-file local.env --with-requirements requirements.txt python app.py
