CREATE OR REPLACE VIEW v_daily_universe AS
SELECT
  u.trade_date,
  u.sid,
  s.symbol_current,
  u.universe_name,
  u.is_member,
  u.eligibility_reason
FROM universe_membership u
LEFT JOIN security_master s USING (sid);
