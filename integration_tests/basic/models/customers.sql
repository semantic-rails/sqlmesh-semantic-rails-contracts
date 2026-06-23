MODEL (
  name semantic_rails.customers,
  kind FULL,
  owner analytics,
  tags (semantic_rails, public),
  audits (not_null_customer_id),
  columns (
    customer_id INTEGER,
    customer_name TEXT,
    customer_status TEXT
  )
);

SELECT
  CAST(1 AS INTEGER) AS customer_id,
  CAST('Ada Lovelace' AS TEXT) AS customer_name,
  CAST('active' AS TEXT) AS customer_status
