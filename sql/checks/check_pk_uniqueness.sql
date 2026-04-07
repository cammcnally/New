SELECT
  table_name,
  duplicate_rows
FROM (
  SELECT
    'security_master (sid)' AS table_name,
    COUNT(*) - COUNT(DISTINCT sid) AS duplicate_rows
  FROM security_master

  UNION ALL

  SELECT
    'prices_1d_unadjusted (sid, trade_date)' AS table_name,
    COALESCE(SUM(cnt - 1), 0) AS duplicate_rows
  FROM (
    SELECT sid, trade_date, COUNT(*) AS cnt
    FROM prices_1d_unadjusted
    GROUP BY sid, trade_date
    HAVING COUNT(*) > 1
  )

  UNION ALL

  SELECT
    'benchmark_prices_daily (sid, trade_date)' AS table_name,
    COALESCE(SUM(cnt - 1), 0) AS duplicate_rows
  FROM (
    SELECT sid, trade_date, COUNT(*) AS cnt
    FROM benchmark_prices_daily
    GROUP BY sid, trade_date
    HAVING COUNT(*) > 1
  )
)
WHERE duplicate_rows > 0;
