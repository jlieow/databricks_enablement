"""Standalone job, task 1: generate a small sample dataset as a Delta table.

Every value this task needs (catalog, schema, row count) arrives as a command
line parameter, set from ${var.*} / ${resources.*} in the resource YAML. The
file itself hard codes nothing environment specific, so the same code runs
unchanged against the dev and prod targets - only the parameter values differ.
"""

import argparse

from pyspark.sql import SparkSession


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--row-count", type=int, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    spark = SparkSession.builder.getOrCreate()

    # The catalog and schema are created by the bundle (resources.catalogs /
    # resources.schemas), so this task only writes its table into the schema.
    table = f"{args.catalog}.{args.schema}.sample_events_raw"

    # A tiny synthetic dataset so the demo needs no external source. row_count
    # comes straight from ${var.row_count}, so prod writes more rows than dev.
    df = spark.range(args.row_count).selectExpr(
        "id AS event_id",
        "id % 5 AS user_id",
        "CAST(rand() * 100 AS DOUBLE) AS amount",
    )
    df.write.mode("overwrite").saveAsTable(table)

    print(f"Wrote {df.count()} rows to {table}")


if __name__ == "__main__":
    main()
