# lib/GitGuard.ps1 — pengaman Git: snapshot, proteksi perubahan pengguna, deny-list destruktif.

$script:WarRoomGitDenied = @(
    'reset --hard',
    'clean -fd', 'clean -f', 'clean -d', 'clean -x',
    'push', 'push --force', 'push -f',
    'filter-branch', 'filter-repo',
    'rebase',
    'branch -D', 'branch -d',
    'checkout -- .', 'restore .',
    'update-ref -d',
    'stash drop', 'stash clear'
)

function Invoke-GitRaw {
    param([Parameter(Mandatory)][string[]]$Args)
    $root = Get-WarRoomRoot
    $out = & git -C $root @Args 2>&1
    return @{ Output = ($out -join "`n"); ExitCode = $LASTEXITCODE }
}

function Get-GitSnapshot {
    $branch = (Invoke-GitRaw @('rev-parse', '--abbrev-ref', 'HEAD')).Output.Trim()
    $head = (Invoke-GitRaw @('rev-parse', '--short', 'HEAD')).Output.Trim()
    $porcelain = (Invoke-GitRaw @('status', '--porcelain=v1')).Output
    $staged = @(); $unstaged = @(); $untracked = @()
    foreach ($line in ($porcelain -split "`n")) {
        if ($line.Length -lt 3) { continue }
        $x = $line.Substring(0, 1); $y = $line.Substring(1, 1)
        $path = $line.Substring(3).Trim()
        if ($x -eq '?' -and $y -eq '?') { $untracked += $path; continue }
        if ($x -ne ' ' -and $x -ne '?') { $staged += $path }
        if ($y -ne ' ' -and $y -ne '?') { $unstaged += $path }
    }
    return [pscustomobject]@{
        branch    = $branch
        head      = $head
        staged    = $staged
        unstaged  = $unstaged
        untracked = $untracked
        dirty     = (($staged.Count + $unstaged.Count) -gt 0)
        hasUntracked = ($untracked.Count -gt 0)
        at        = Get-WarRoomUtcNow
    }
}

function Test-GitCommandSafe {
    # True bila aman (tidak memuat pola destruktif).
    param([Parameter(Mandatory)][string]$Command)
    $c = $Command.ToLowerInvariant()
    if ($c -notmatch '^\s*git\b') { return $true }
    foreach ($pat in $script:WarRoomGitDenied) {
        if ($c -match [regex]::Escape($pat)) { return $false }
    }
    return $true
}

function Protect-UserChanges {
    # Simpan snapshot perubahan pengguna agar tidak hilang saat kerja otonom.
    $snap = Get-GitSnapshot
    $path = Join-Path (Get-WarRoomStateDir) 'user-changes.json'
    Write-WarRoomJsonFile -Path $path -Object $snap
    Write-WarRoomEvent -Category 'git' -Message 'snapshot perubahan pengguna' -Data @{
        branch = $snap.branch; head = $snap.head; staged = $snap.staged.Count
        unstaged = $snap.unstaged.Count; untracked = $snap.untracked.Count
    } | Out-Null
    return $snap
}

function New-WarRoomBranch {
    param([Parameter(Mandatory)][string]$Name)
    $cur = Get-GitSnapshot
    if ($cur.dirty) {
        throw "Working tree tidak bersih (ada perubahan staged/unstaged). Isolasi dulu sebelum membuat cabang."
    }
    $exists = (Invoke-GitRaw @('rev-parse', '--verify', "--quiet", "refs/heads/$Name")).ExitCode -eq 0
    if ($exists) {
        Write-WarRoomEvent -Category 'git' -Message "cabang $Name sudah ada" -Level 'warn' | Out-Null
        return $Name
    }
    $r = Invoke-GitRaw @('checkout', '-b', $Name)
    if ($r.ExitCode -ne 0) { throw "Gagal membuat cabang ${Name}: $($r.Output)" }
    Write-WarRoomEvent -Category 'git' -Message "cabang isolasi dibuat: $Name" | Out-Null
    return $Name
}

function Get-GitDiffStat {
    $r = Invoke-GitRaw @('diff', '--stat')
    return $r.Output
}

function Get-GitDiff {
    $r = Invoke-GitRaw @('diff')
    return $r.Output
}
