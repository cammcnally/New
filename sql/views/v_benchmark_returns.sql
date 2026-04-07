CREATE OR REPLACE VIEW v_benchmark_returns AS
WITH ordered AS (
  SELECT
    sid,
    trade_date,
    close,
    LAG(close) OVER (PARTITION BY sid ORDER BY trade_date) AS prev_close
  FROM benchmark_prices_daily
)
SELECT
  sid,
  trade_date,
  close,
  prev_close,
  CASE
    WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
    ELSE (close / prev_close) - 1
  END AS return_1d
FROM ordered;
