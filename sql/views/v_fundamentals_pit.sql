CREATE OR REPLACE VIEW v_fundamentals_pit AS
SELECT
  sid,
  trade_date,
  metric_name,
  metric_value,
  unit,
  accession_no,
  accepted_at,
  loaded_at
FROM fundamentals_asof_daily;
