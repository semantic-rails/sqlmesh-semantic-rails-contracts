MODEL (
  name semantic_rails.orders,
  kind FULL,
  owner analytics,
  tags (semantic_rails),
  audits (not_null_customer_id),
  columns (
    order_id INTEGER,
    customer_id INTEGER
  )
);

SELECT
  CAST(100 AS INTEGER) AS order_id,
  CAST(1 AS INTEGER) AS customer_id
