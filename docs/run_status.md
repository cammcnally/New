# Run Status Template

## Summary

- status: `planned|running|completed|completed_with_warnings|blocked_cleanly|partial_progress`
- run_started_at:
- run_finished_at:
- authoritative_command:
- resume_command:
- output_root:

## Build References

- dataset_build_id:
- export_panel_version_id:
- dataset_manifest_path:
- export_manifest_path:
- verification_summary_path:

## Stage Results

| Stage | Result | Command | Primary output | Notes |
| ------ | ------ | ------ | ------ | ------ |
| dependency_sync | | | | |
| canonical_market_data | | | | |
| verify_market_data | | | | |
| export_panel | | | | |
| pipeline_run | | | | |
| finalize_status | | | | |

## Verification Guards

| Guard | Result | Evidence path | Notes |
| ------ | ------ | ------ | ------ |
| schema_guard | | | |
| docs_sync_guard | | | |
| pit_guard | | | |
| compat_guard | | | |
| bridge_guard | | | |
| verification_guard | | | |

## Output Inventory

- canonical data updated:
- exported panel path:
- pipeline output dir:
- verification JSON:
- verification Markdown:
- lineage summary JSON:
- final report path:
- status summary path:

## Deferred Components

- deferred components observed:
- deferred components reported in manifests:
- impact on current run:

## Blockers Or Warnings

- blocker summary:
- warning summary:
- next rerun command:

## Notes

- compatibility impact:
- docs synchronized:
- remaining follow-up:
