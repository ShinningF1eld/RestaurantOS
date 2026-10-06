[CmdletBinding()]
param(
    [string]$PythonExecutable,
    [string[]]$Gate,
    [switch]$ExternalServices,
    [switch]$NoInstall,
    [switch]$SkipBuild,
    [switch]$SkipDatabase,
    [switch]$SkipBrowser,
    [switch]$SkipSecrets
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendPython = if ($PythonExecutable) {
    if ([IO.Path]::IsPathRooted($PythonExecutable)) {
        [IO.Path]::GetFullPath($PythonExecutable)
    } else {
        [IO.Path]::GetFullPath((Join-Path $repositoryRoot $PythonExecutable))
    }
} else { Join-Path $repositoryRoot "backend/.venv/Scripts/python.exe" }
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Create backend/.venv and install the development lock first; see docs/testing/README.md."
}

$allGates = @("baseline", "backend-static", "frontend-static", "backend-unit",
    "backend-integration", "frontend-tests", "frontend-build", "migrations", "browser", "image")
$selectedGates = if ($Gate) { @($Gate) } else { @($allGates) }
if ($SkipBuild) { $selectedGates = @($selectedGates | Where-Object { $_ -notin @("frontend-build", "image") }) }
if ($SkipDatabase) { $selectedGates = @($selectedGates | Where-Object { $_ -notin @("backend-integration", "migrations", "browser", "image") }) }
if ($SkipBrowser) { $selectedGates = @($selectedGates | Where-Object { $_ -ne "browser" }) }
if ($SkipSecrets) { $selectedGates = @($selectedGates | Where-Object { $_ -ne "baseline" }) }
if ($selectedGates.Count -eq 0) { throw "No validation gates selected." }

$runnerArguments = @((Join-Path $PSScriptRoot "validate.py"))
if ($Gate -or $SkipBuild -or $SkipDatabase -or $SkipBrowser -or $SkipSecrets) {
    foreach ($selectedGate in $selectedGates) { $runnerArguments += @("--gate", $selectedGate) }
}
if ($ExternalServices) { $runnerArguments += "--external-services" }
if ($NoInstall) { $runnerArguments += "--no-install" }

Push-Location $repositoryRoot
try {
    & $backendPython @runnerArguments
    if ($LASTEXITCODE -ne 0) { throw "Validation failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
