"""Orchestrated job, task 3: read the pipeline's output and write a final table.

This runs only after the pipeline task finishes, so customer_summary already
exists. It ranks customers by spend and writes customer_final - the last step of
the ingest -> pipeline -> summarize chain, proving the whole DAG ran in order.
"""

import argparse

from pyspark.sql import SparkSession, functions as F, Window


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    spark = SparkSession.builder.getOrCreate()

    source = f"{args.catalog}.{args.schema}.customer_summary"
    target = f"{args.catalog}.{args.schema}.customer_final"

    ranked = spark.table(source).withColumn(
        "spend_rank",
        F.rank().over(Window.orderBy(F.col("total_amount").desc())),
    )
    ranked.write.mode("overwrite").saveAsTable(target)

    print(f"Wrote {ranked.count()} rows to {target}")


if __name__ == "__main__":
    main()
