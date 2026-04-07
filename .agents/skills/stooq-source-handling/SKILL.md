# Stooq source handling

Canonical checklist for Stooq supplemental OHLCV ingestion, fallbacks, and conflict diagnostics. Cursor projects a non-authoritative copy under `.cursor/skills/stooq-source-handling/SKILL.md` from `AGENTS.md` skills registry.

## When to use

- Stooq daily or intraday ingest paths need alignment with ingestion contracts.
- Raw vs adjusted conflicts or duplicate symbol handling.

## References

- `docs/data_contract.md`
- `market_data/raw/ingest_stooq_*.py`
