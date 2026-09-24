"""Orchestrated job, task 1: write the raw orders table the pipeline consumes.

This is the input the downstream pipeline reads. Writing it from a job task
(rather than generating it inside the pipeline) is what makes this an
orchestration demo: the job produces data, then hands off to the pipeline.
"""

import argparse

from pyspark.sql import SparkSession


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    spark = SparkSession.builder.getOrCreate()

    table = f"{args.catalog}.{args.schema}.orders_raw"

    df = spark.createDataFrame(
        [
            (1, 101, 250.00),
            (2, 101, 125.50),
            (3, 102, 500.00),
            (4, 103, 75.25),
            (5, 102, 60.00),
            (6, 103, 310.75),
        ],
        ["order_id", "customer_id", "order_amount"],
    )
    df.write.mode("overwrite").saveAsTable(table)

    print(f"Wrote {df.count()} rows to {table}")


if __name__ == "__main__":
    main()
