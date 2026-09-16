[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$SkipDatabase,
    [switch]$SkipSecrets
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $repositoryRoot "backend/.venv/Scripts/python.exe"
$secretHook = Join-Path $repositoryRoot "backend/.venv/Scripts/detect-secrets-hook.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "`n==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Missing backend/.venv. Follow the root README setup instructions first."
}

Push-Location $repositoryRoot
try {
    Invoke-Checked "Docker Compose configuration" { docker compose config --quiet }
    Invoke-Checked "Python dependency integrity" { & $backendPython -m pip check }

    if (-not $SkipSecrets) {
        if (-not (Test-Path -LiteralPath $secretHook)) {
            throw "detect-secrets is not installed. Install backend/requirements-dev.txt."
        }

        $trackedFiles = @(git ls-files --cached --others --exclude-standard)
        Invoke-Checked "Tracked and candidate file secret scan" {
            & $secretHook --baseline .secrets.baseline @trackedFiles
        }
    }

    Push-Location (Join-Path $repositoryRoot "backend")
    try {
        Invoke-Checked "Backend Ruff" { & $backendPython -m ruff check app tests }
        Invoke-Checked "Backend typed-schema mypy scope" {
            & $backendPython -m mypy app/schemas
        }
        if (-not $SkipDatabase) {
            $backendEnv = Join-Path $repositoryRoot "backend/.env"
            if (
                [string]::IsNullOrWhiteSpace($env:DATABASE_URL) -and
                -not (Test-Path -LiteralPath $backendEnv)
            ) {
                throw "Set DATABASE_URL or copy backend/.env.example to backend/.env."
            }
            Invoke-Checked "Alembic upgrade to head" { & $backendPython -m alembic upgrade head }
            Invoke-Checked "Alembic model drift check" { & $backendPython -m alembic check }
        }

        Invoke-Checked "Backend tests" { & $backendPython -m pytest }
    }
    finally {
        Pop-Location
    }

    Push-Location (Join-Path $repositoryRoot "frontend")
    try {
        Invoke-Checked "Frontend ESLint" { npm run lint }
        Invoke-Checked "Frontend TypeScript" { npm run typecheck }
        if (-not $SkipBuild) {
            Invoke-Checked "Frontend production build" { npm run build }
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "`nValidation completed successfully." -ForegroundColor Green
}
finally {
    Pop-Location
}
