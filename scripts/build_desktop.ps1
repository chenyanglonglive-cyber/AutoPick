param(
    [string]$Python = "python",
    [string]$Pnpm = "pnpm"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location "$repoRoot\frontend"
& $Pnpm build
Pop-Location

& $Python -m PyInstaller --noconfirm --clean "$repoRoot\AutoPick.spec"
Write-Host "Desktop build: $repoRoot\dist\AutoPick\AutoPick.exe"
