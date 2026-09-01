"""Transform task: aggregate the raw encounters table written by the ingest task.

This task runs only after `ingest` succeeds - that ordering is declared with
`depends_on` in databricks.yml, not in this file. It reads the raw table and
writes a per-district summary table alongside it.
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

    source = f"{args.catalog}.{args.schema}.encounters_raw"
    target = f"{args.catalog}.{args.schema}.encounters_by_district"

    summary = (
        spark.table(source)
        .groupBy("district_id")
        .agg(
            F.count("*").alias("encounter_count"),
            F.round(F.avg("length_of_stay_days"), 2).alias("avg_length_of_stay_days"),
            F.round(F.sum("cost_usd"), 2).alias("total_cost_usd"),
        )
        .orderBy("district_id")
    )
    summary.write.mode("overwrite").saveAsTable(target)

    print(f"Wrote {summary.count()} rows to {target}")


if __name__ == "__main__":
    main()
