$workspaceRoot = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $workspaceRoot ".local"
$cacheRoot = Join-Path $localRoot "cache"
$tempRoot = Join-Path $localRoot "temp"
$pipConfig = Join-Path $localRoot "pip\\pip.ini"
$venvActivate = Join-Path $workspaceRoot ".venv\\Scripts\\Activate.ps1"

$paths = @(
    $localRoot,
    $cacheRoot,
    (Join-Path $cacheRoot "pip"),
    (Join-Path $cacheRoot "ms-playwright"),
    (Join-Path $cacheRoot "uv"),
    (Join-Path $cacheRoot "pypoetry"),
    (Join-Path $cacheRoot "npm"),
    (Join-Path $localRoot "python-user"),
    $tempRoot
)

foreach ($path in $paths) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

$envVars = @{
    PIP_CONFIG_FILE = $pipConfig
    PIP_CACHE_DIR = Join-Path $cacheRoot "pip"
    PYTHONUSERBASE = Join-Path $localRoot "python-user"
    TEMP = $tempRoot
    TMP = $tempRoot
    TMPDIR = $tempRoot
    XDG_CACHE_HOME = $cacheRoot
    PLAYWRIGHT_BROWSERS_PATH = Join-Path $cacheRoot "ms-playwright"
    UV_CACHE_DIR = Join-Path $cacheRoot "uv"
    POETRY_CACHE_DIR = Join-Path $cacheRoot "pypoetry"
    NPM_CONFIG_CACHE = Join-Path $cacheRoot "npm"
}

foreach ($entry in $envVars.GetEnumerator()) {
    Set-Item -Path ("Env:" + $entry.Key) -Value $entry.Value
}

if (-not (Test-Path $venvActivate)) {
    Write-Error "Local virtual environment not found at $venvActivate"
    exit 1
}

. $venvActivate

$pythonPath = (Get-Command python).Source
$pipPath = (Get-Command pip).Source

Write-Host "Project environment is active."
Write-Host "python => $pythonPath"
Write-Host "pip    => $pipPath"
Write-Host "TEMP   => $env:TEMP"
