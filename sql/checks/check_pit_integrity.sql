SELECT
  check_name,
  violating_rows
FROM (
  SELECT
    'fundamentals_asof_daily accepted_at after trade_date' AS check_name,
    COUNT(*) AS violating_rows
  FROM fundamentals_asof_daily
  WHERE accepted_at > (CAST(trade_date AS TIMESTAMP) + INTERVAL 1 DAY - INTERVAL 1 MICROSECOND)

  UNION ALL

  SELECT
    'macro_asof_daily observation_date after asof_date' AS check_name,
    COUNT(*) AS violating_rows
  FROM macro_asof_daily
  WHERE observation_date > asof_date
)
WHERE violating_rows > 0;
