# Standalone Python Lakeflow Declarative Pipeline.
#
# raw_orders is a small in-pipeline sample source so the demo runs end-to-end
# with no pre-existing table. customer_summary reads it by name (datasets in the
# same pipeline are referenced with spark.read.table) and aggregates per
# customer.

from pyspark import pipelines as dp
from pyspark.sql import functions as F


@dp.materialized_view
def raw_orders():
    return spark.createDataFrame(
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


@dp.materialized_view
def customer_summary():
    return (
        spark.read.table("raw_orders")
        .groupBy("customer_id")
        .agg(
            F.sum("order_amount").alias("total_amount"),
            F.count("*").alias("order_count"),
        )
    )
