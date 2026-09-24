"""Dead-simple job script for the "apps resource block" demo.

The whole point is the ONE parameter it prints. The name arrives as the job's
`app_name` parameter (see resources/job.yml): it defaults to ${var.app_name} for
a manual run, and the app OVERRIDES it at run time by passing its own name when
the button calls jobs.run_now. So this script never hard-codes the name; it just
echoes whatever it was handed.
"""

import sys

# spark_python_task passes `parameters:` as command-line args, so the app name
# arrives as argv[1].
app_name = sys.argv[1] if len(sys.argv) > 1 else "(no app name passed)"

print(f"Triggered by app: {app_name}")
