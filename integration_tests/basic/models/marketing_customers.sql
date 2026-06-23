MODEL (
  name marketing.customers,
  kind FULL,
  owner marketing,
  columns (
    customer_id INTEGER,
    campaign_code TEXT
  )
);

SELECT
  CAST(1 AS INTEGER) AS customer_id,
  CAST('welcome' AS TEXT) AS campaign_code
