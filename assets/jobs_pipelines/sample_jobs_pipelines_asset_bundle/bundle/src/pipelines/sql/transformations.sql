-- Standalone SQL Lakeflow Declarative Pipeline.
--
-- raw_orders is a small in-pipeline sample source so the demo runs end-to-end
-- with no pre-existing table. customer_summary reads it by name (datasets in the
-- same pipeline are referenced directly, no catalog/schema prefix needed) and
-- aggregates per customer.

CREATE OR REFRESH MATERIALIZED VIEW raw_orders AS
SELECT * FROM VALUES
  (1, 101, 250.00),
  (2, 101, 125.50),
  (3, 102, 500.00),
  (4, 103,  75.25),
  (5, 102,  60.00),
  (6, 103, 310.75)
AS orders(order_id, customer_id, order_amount);

CREATE OR REFRESH MATERIALIZED VIEW customer_summary AS
SELECT
  customer_id,
  SUM(order_amount) AS total_amount,
  COUNT(*)          AS order_count
FROM raw_orders
GROUP BY customer_id;
