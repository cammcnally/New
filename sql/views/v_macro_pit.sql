CREATE OR REPLACE VIEW v_macro_pit AS
SELECT
  series_id,
  asof_date,
  observation_date,
  value,
  selected_vintage_date,
  selected_available_from_ts_utc,
  selection_rule_version,
  built_at_utc
FROM macro_asof_daily;
