"""Ingest task: generate a small synthetic encounters dataset and write it as a
Delta table.

Every value this task needs (catalog, schema, row count) arrives as a command
line parameter, set from `${var.*}` in databricks.yml. The file itself hard
codes nothing environment specific, so the same code runs unchanged against the
dev and prod targets - only the parameter values differ.

The data is synthetic patient-encounter events for two fictional health
districts. It mirrors the shape of the enablement scenario without using any
real or identifying data.
"""

import argparse

from pyspark.sql import SparkSession, functions as F


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
    table = f"{args.catalog}.{args.schema}.encounters_raw"

    # A tiny synthetic dataset so the demo needs no external source. row_count
    # comes straight from ${var.row_count}, so prod writes more rows than dev.
    districts = ["northmoor_district", "eldervale_district"]
    encounter_types = ["outpatient_visit", "inpatient_admission", "lab_result"]

    df = (
        spark.range(args.row_count)
        .withColumn("encounter_id", F.col("id"))
        .withColumn(
            "district_id",
            F.element_at(F.array(*[F.lit(d) for d in districts]), (F.col("id") % 2 + 1).cast("int")),
        )
        .withColumn(
            "encounter_type",
            F.element_at(
                F.array(*[F.lit(t) for t in encounter_types]),
                (F.col("id") % 3 + 1).cast("int"),
            ),
        )
        .withColumn("length_of_stay_days", (F.rand(seed=7) * 10).cast("int"))
        .withColumn("cost_usd", F.round(F.rand(seed=11) * 5000, 2))
        .drop("id")
    )
    df.write.mode("overwrite").saveAsTable(table)

    print(f"Wrote {df.count()} rows to {table}")


if __name__ == "__main__":
    main()
