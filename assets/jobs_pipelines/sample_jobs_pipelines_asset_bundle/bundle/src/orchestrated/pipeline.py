# Orchestrated Python Lakeflow Declarative Pipeline.
#
# Unlike the standalone pipelines, this one does NOT generate its own source. It
# reads the orders_raw table that the orchestrated job's ingest task wrote, then
# publishes customer_summary from it. The job task ordering guarantees orders_raw
# exists before this pipeline runs.
#
# The source catalog/schema are not hard coded: they arrive through the
# pipeline's `configuration` (set in orchestrated_pipeline.yml) and are read here
# with spark.conf.get(...) - the pipeline equivalent of a job task's parameters.

from pyspark import pipelines as dp
from pyspark.sql import functions as F

source_catalog = spark.conf.get("source_catalog")
source_schema = spark.conf.get("source_schema")
source_table = f"{source_catalog}.{source_schema}.orders_raw"


@dp.materialized_view
def customer_summary():
    return (
        spark.read.table(source_table)
        .groupBy("customer_id")
        .agg(
            F.sum("order_amount").alias("total_amount"),
            F.count("*").alias("order_count"),
        )
    )
