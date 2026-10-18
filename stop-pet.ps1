# Stop the xinyuehu pet watchdog and the pet itself.
#
# Separated from the .cmd wrappers on purpose: killing by PID needs JSON
# parsing of the lock files, and `for /f ... in ('type "a path with spaces"')`
# in batch is fragile around quoting. ASCII-only for the same reason the .cmd
# files are (OEM codepage).
param(
  [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
$dshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }

function Stop-ByLock {
  param([string]$Path, [string]$Label)

  if (-not (Test-Path -LiteralPath $Path)) { return }
  $pidValue = 0
  try {
    $pidValue = [int](Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json).pid
  } catch {
    $pidValue = 0
  }
  if ($pidValue -gt 0) {
    try {
      Stop-Process -Id $pidValue -Force -ErrorAction Stop
      if (-not $Quiet) { Write-Host "[ok] $Label stopped (pid $pidValue)." }
    } catch {
      if (-not $Quiet) { Write-Host "[i] $Label pid $pidValue was not running." }
    }
  }
  Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

# Watchdog first: otherwise it would relaunch the pet immediately after.
Stop-ByLock -Path (Join-Path $dshHome 'xinyuehu-pet-watchdog.lock') -Label 'Watchdog'
Stop-ByLock -Path (Join-Path $dshHome 'xinyuehu-pet.lock') -Label 'Pet'

# Belt and braces: any stray instance started by hand.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'run_pet_watchdog\.py|run_pet\.py' } |
  ForEach-Object {
    try {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
      if (-not $Quiet) { Write-Host "[ok] stopped stray process pid $($_.ProcessId)." }
    } catch { }
  }

exit 0
