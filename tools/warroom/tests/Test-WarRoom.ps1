# tools/warroom/tests/Test-WarRoom.ps1 — uji mandiri War Room (tanpa dependensi eksternal).
# Menjalankan uji anggaran, reservasi bersamaan, fail-closed, kontrol, GitGuard, redaksi.
# Pemakaian: powershell -NoProfile -ExecutionPolicy Bypass -File tools/warroom/tests/Test-WarRoom.ps1

$ErrorActionPreference = 'Continue'
$script:Pass = 0
$script:Fail = 0
$script:Failures = @()

function Assert-True {
    param([bool]$Condition, [string]$Name, [string]$Detail = '')
    if ($Condition) { $script:Pass++; Write-Host "  [PASS] $Name" -ForegroundColor Green }
    else { $script:Fail++; $script:Failures += $Name; Write-Host "  [FAIL] $Name $Detail" -ForegroundColor Red }
}
function Assert-False { param([bool]$Condition, [string]$Name, [string]$Detail = '') ; Assert-True (-not $Condition) $Name $Detail }
function Assert-Eq { param($Expected, $Actual, [string]$Name) ; Assert-True ($Expected -eq $Actual) $Name "(harap=$Expected aktual=$Actual)" }

$libDir = (Resolve-Path (Join-Path $PSScriptRoot '..\lib')).Path
$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

function New-TestEnv {
    param([hashtable]$Overrides = @{})
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("wr-test-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $monthly = if ($Overrides.ContainsKey('MonthlyBudgetIDR')) { $Overrides.MonthlyBudgetIDR } else { 100 }
    $target  = if ($Overrides.ContainsKey('TargetAutomationBudgetIDR')) { $Overrides.TargetAutomationBudgetIDR } else { 40 }
    $warning = if ($Overrides.ContainsKey('WarningThresholdIDR')) { $Overrides.WarningThresholdIDR } else { 25 }
    $reduced = if ($Overrides.ContainsKey('ReducedModeThresholdIDR')) { $Overrides.ReducedModeThresholdIDR } else { 30 }
    $hard    = if ($Overrides.ContainsKey('HardPauseThresholdIDR')) { $Overrides.HardPauseThresholdIDR } else { 50 }
    $usd     = if ($Overrides.ContainsKey('UsdToIdr')) { $Overrides.UsdToIdr } else { 1 }
    $cfgPath = Join-Path $dir 'test.options.psd1'
    $content = @"
@{
    Model = 'deepseek/deepseek-flash'
    Agents = @{ Lead = 'lead-engineer'; Code = 'code-engineer'; Quant = 'quant-analyst'; QA = 'qa-engineer'; Reviewer = 'reviewer' }
    MonthlyBudgetIDR = $monthly
    TargetAutomationBudgetIDR = $target
    WarningThresholdIDR = $warning
    ReducedModeThresholdIDR = $reduced
    HardPauseThresholdIDR = $hard
    PerCycleBudgetIDR = 10
    MaxCyclesPerDay = 3
    MaxDiscussionRounds = 2
    MaxConcurrentModelTasks = 2
    MaxRepairAttempts = 2
    MaxOutputTokensPerCall = 4096
    NormalIdleIntervalMinutes = 30
    FailureBackoffMinutes = 60
    UsdToIdr = $usd
    ExchangeRateVerifiedDate = 'test'
    PriceVerifiedDate = 'test'
    Rates = @{
        'deepseek/deepseek-flash' = @{ InputCacheHitPerMillionUSD = 0.006; InputCacheMissPerMillionUSD = 0.30; OutputPerMillionUSD = 1.20 }
    }
    DefaultRate = @{ InputCacheHitPerMillionUSD = 0.006; InputCacheMissPerMillionUSD = 0.30; OutputPerMillionUSD = 1.20 }
}
"@
    Set-Content -LiteralPath $cfgPath -Value $content -Encoding UTF8
    $env:WARROOM_STATE_DIR = $dir
    $env:WARROOM_CONFIG_PATH = $cfgPath
    return $dir
}

# Muat modul.
. (Join-Path $libDir 'Common.ps1')
. (Join-Path $libDir 'EventLog.ps1')
. (Join-Path $libDir 'StateManager.ps1')
. (Join-Path $libDir 'GitGuard.ps1')
. (Join-Path $libDir 'BudgetManager.ps1')
. (Join-Path $libDir 'BacklogManager.ps1')

Write-Host "`n== Test War Room ==`n" -ForegroundColor Cyan

# --- T1: reservasi ditolak bila melampaui ambang hard pause ---
Write-Host "T1 anggaran: tolak sebelum melampaui hard pause" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
$r1 = Reserve-Budget -ReservationId 'r1' -EstimatedCostIDR 30
$r2 = Reserve-Budget -ReservationId 'r2' -EstimatedCostIDR 30
Assert-True ($r1.granted) "reservasi pertama diterima (30<50)"
Assert-False ($r2.granted) "reservasi kedua ditolak (30+30>50)" "reason=$($r2.reason)"
Assert-Eq 'hard-pause-threshold' $r2.reason "alasan penolakan = hard-pause-threshold"
Release-Budget -ReservationId 'r1'
Release-Budget -ReservationId 'r2'

# --- T2: penggunaan tidak diketahui tidak dihitung nol ---
Write-Host "T2 fail-safe: usage unknown != 0" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
Reserve-Budget -ReservationId 'u1' -EstimatedCostIDR 7 | Out-Null
Commit-Budget -ReservationId 'u1' -Source 'unknown' -Role 'qa' -Agent 'qa-engineer' -Model 'deepseek/deepseek-flash' | Out-Null
$spent = Get-BudgetSpentIDR
Assert-True ($spent -ge 7) "biaya unknown dihitung konservatif (spent=$spent)"
$entries = Get-UsageEntries
Assert-True ([bool]$entries[-1].unknown) "entri ditandai unknown"

# --- T3: reservasi bersamaan tidak double-spend ---
Write-Host "T3 concurrency: reservasi bersamaan" -ForegroundColor Cyan
$dir3 = New-TestEnv
Initialize-WarRoomState
$cfg3 = $env:WARROOM_CONFIG_PATH
$stateDir3 = $env:WARROOM_STATE_DIR
$jobs = @()
foreach ($n in 1..2) {
    $jobs += Start-Job -ArgumentList $libDir, $stateDir3, $cfg3, $n -ScriptBlock {
        param($libDir, $stateDir, $psd1, $n)
        $env:WARROOM_STATE_DIR = $stateDir
        $env:WARROOM_CONFIG_PATH = $psd1
        . (Join-Path $libDir 'Common.ps1')
        . (Join-Path $libDir 'EventLog.ps1')
        . (Join-Path $libDir 'StateManager.ps1')
        . (Join-Path $libDir 'BudgetManager.ps1')
        $r = Reserve-Budget -ReservationId "job$n" -EstimatedCostIDR 30
        [pscustomobject]@{ granted = $r.granted }
    }
}
$null = Wait-Job -Job $jobs -Timeout 60
$results = @($jobs | ForEach-Object { Receive-Job -Job $_ } | Where-Object { $_ -ne $null })
$jobs | Remove-Job -Force -ErrorAction SilentlyContinue
$grantedCount = @($results | Where-Object { $_.granted }).Count
Assert-Eq 1 $grantedCount "hanya satu reservasi granted (total<=50)"
$resv = Get-BudgetReservedIDR
Assert-True ($resv -le 50) "total cadangan tidak melampaui hard pause (=$resv)"

# --- T4: transisi ambang warning/reduced/paused ---
Write-Host "T4 transisi ambang" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
Commit-Budget -ReservationId 'x' -Source 'reported' -ReportedCostUSD 26 -Model 'deepseek/deepseek-flash' | Out-Null
Assert-Eq 'warning' (Get-BudgetStatus).mode "spent 26 -> warning"
Commit-Budget -ReservationId 'x' -Source 'reported' -ReportedCostUSD 6 -Model 'deepseek/deepseek-flash' | Out-Null
Assert-Eq 'reduced' (Get-BudgetStatus).mode "spent 32 -> reduced"
Commit-Budget -ReservationId 'x' -Source 'reported' -ReportedCostUSD 10 -Model 'deepseek/deepseek-flash' | Out-Null
Assert-Eq 'paused' (Get-BudgetStatus).mode "spent 42 -> paused"
Assert-False (Test-BudgetAvailable -EstimatedCostIDR 1) "panggilan baru ditolak saat paused"

# --- T5: pause/stop mencegah panggilan baru ---
Write-Host "T5 kontrol pause/stop" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
Assert-True (Test-WarRoomCanLaunch) "default boleh meluncurkan"
Set-WarRoomControl -Pause | Out-Null
Assert-False (Test-WarRoomCanLaunch) "pause mencegah peluncuran"
Set-WarRoomControl -Resume | Out-Null
Assert-True (Test-WarRoomCanLaunch) "resume mengizinkan lagi"
Set-WarRoomControl -Stop | Out-Null
Assert-False (Test-WarRoomCanLaunch) "stop mencegah peluncuran"

# --- T6: ledger rusak -> fail closed ---
Write-Host "T6 fail-closed ledger rusak" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
Add-Content -LiteralPath (Get-UsageLedgerPath) -Value '{ ini json rusak' -Encoding UTF8
Assert-False (Test-LedgerHealthy) "ledger tidak sehat terdeteksi"
Assert-False (Test-BudgetAvailable -EstimatedCostIDR 1) "panggilan ditolak saat ledger rusak"

# --- T7: GitGuard deny-list + proteksi untracked ---
Write-Host "T7 GitGuard" -ForegroundColor Cyan
New-TestEnv | Out-Null
Assert-False (Test-GitCommandSafe -Command 'git reset --hard HEAD') "menolak git reset --hard"
Assert-False (Test-GitCommandSafe -Command 'git clean -fd') "menolak git clean"
Assert-False (Test-GitCommandSafe -Command 'git push origin main') "menolak git push"
Assert-True (Test-GitCommandSafe -Command 'git status') "mengizinkan git status"
$snap = Protect-UserChanges
Assert-True ($snap.PSObject.Properties.Name -contains 'untracked') "snapshot memuat daftar untracked"
Assert-True ($snap.untracked -contains 'Agent/') "untracked pengguna (Agent/) terlindungi"

# --- T8: redaksi rahasia ---
Write-Host "T8 redaksi rahasia" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
$red = Protect-WarRoomSecret 'OPENAI_API_KEY=sk-abcdef0123456789 dan Bearer abcdefghijklmnop123'
Assert-False ($red -match 'sk-abcdef') "API key diredaksi"
Write-WarRoomEvent -Category 'test' -Message 'token sk-abcdef0123456789' | Out-Null
$eventsRaw = Get-Content -LiteralPath (Join-Path (Get-WarRoomStateDir) 'events.jsonl') -Raw
Assert-False ($eventsRaw -match 'sk-abcdef') "event log bebas API key"

# --- T9: backlog prioritas ---
Write-Host "T9 backlog" -ForegroundColor Cyan
New-TestEnv | Out-Null
Initialize-WarRoomState
Add-BacklogItem -Title 'A' -Severity 'low' -Confidence 'low' -Effort 'L' | Out-Null
Add-BacklogItem -Title 'B' -Severity 'critical' -Confidence 'high' -Effort 'S' | Out-Null
$next = Get-NextBacklogItem
Assert-Eq 'B' $next.title "item prioritas tertinggi dipilih"

# --- Ringkasan ---
Write-Host "`n== Hasil: $script:Pass lulus, $script:Fail gagal ==" -ForegroundColor $(if ($script:Fail -eq 0) { 'Green' } else { 'Red' })
if ($script:Fail -gt 0) {
    Write-Host "Gagal:" -ForegroundColor Red
    $script:Failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
exit 0
