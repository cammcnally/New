#Requires -Version 5.1
<#
.SYNOPSIS
  Point this clone at repo-scoped hooks under .githooks (core.hooksPath).

.NOTES
  Run from repository root: .\tools\setup_repo_git_hooks.ps1
  All paths stay under the approved E-drive repo root.
#>
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

git config core.hooksPath .githooks
$configured = git config --get core.hooksPath
if ($configured -ne ".githooks") {
    Write-Error "core.hooksPath is '$configured'; expected '.githooks'"
    exit 1
}
Write-Host "OK: core.hooksPath=$configured"
Write-Host "Pre-commit uses: uv run pre-commit run --hook-stage pre-commit"
Write-Host "Auto-push (post-commit/post-rewrite) requires REPO_AUTO_PUSH_ENABLED=1; see docs/repo_sync_policy.md"
exit 0
