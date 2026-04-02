SELECT
  check_name,
  failing_rows
FROM (
  SELECT
    'prices_1d_unadjusted null critical fields' AS check_name,
    COUNT(*) AS failing_rows
  FROM prices_1d_unadjusted
  WHERE sid IS NULL OR trade_date IS NULL OR close IS NULL

  UNION ALL

  SELECT
    'universe_membership invalid boolean state' AS check_name,
    COUNT(*) AS failing_rows
  FROM universe_membership
  WHERE is_member IS NULL
)
WHERE failing_rows > 0;
