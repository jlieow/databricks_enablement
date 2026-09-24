"""Standalone job, task 2: aggregate the raw table written by the ingest task.

This task runs only after `ingest` succeeds - that ordering is declared with
`depends_on` in the resource YAML, not in this file. It reads the raw table and
writes a per-user summary table alongside it.
"""

import argparse

from pyspark.sql import SparkSession, functions as F


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    spark = SparkSession.builder.getOrCreate()

    source = f"{args.catalog}.{args.schema}.sample_events_raw"
    target = f"{args.catalog}.{args.schema}.sample_events_by_user"

    summary = (
        spark.table(source)
        .groupBy("user_id")
        .agg(
            F.count("*").alias("event_count"),
            F.round(F.sum("amount"), 2).alias("total_amount"),
        )
        .orderBy("user_id")
    )
    summary.write.mode("overwrite").saveAsTable(target)

    print(f"Wrote {summary.count()} rows to {target}")


if __name__ == "__main__":
    main()
