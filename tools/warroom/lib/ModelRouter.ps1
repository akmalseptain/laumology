# lib/ModelRouter.ps1 - routing model per peran/agen + tuning efisiensi konteks.
# Bergantung pada Common.ps1 (Get-WarRoomConfig). Aman bila kunci config tidak ada
# (default konservatif = model utama, tanpa pembatas).

function Get-WarRoomTuning {
    # Baca opsi efisiensi dari config dengan default aman (backward-compatible).
    $cfg = Get-WarRoomConfig
    function __get([string]$k, $d) { if ($cfg.ContainsKey($k)) { $cfg[$k] } else { $d } }
    $t = [pscustomobject]@{
        EnableCrossTalk  = [bool](__get 'EnableCrossTalk' $true)
        MaxAgentRetries  = [int](__get 'MaxAgentRetries' 1)
        PlanMaxChars     = [int](__get 'PlanMaxChars' 6000)
        FindingsMaxChars = [int](__get 'FindingsMaxChars' 8000)
        ReactionsMaxChars = [int](__get 'ReactionsMaxChars' 3000)
        RepoMapMaxChars  = [int](__get 'RepoMapMaxChars' 6000)
    }
    return $t
}

function Resolve-WarRoomModel {
    # Pilih model: ByAgent > ByRole > Tier (fast/strong) > Default > cfg.Model.
    param(
        [string]$Agent = '',
        [string]$Role = '',
        [ValidateSet('fast', 'strong', '')][string]$Tier = ''
    )
    $cfg = Get-WarRoomConfig
    $models = if ($cfg.ContainsKey('Models')) { $cfg.Models } else { @{} }
    if ($models -and $models.ContainsKey('ByAgent') -and $Agent -and $models.ByAgent.ContainsKey($Agent)) {
        return [string]$models.ByAgent[$Agent]
    }
    if ($models -and $models.ContainsKey('ByRole') -and $Role -and $models.ByRole.ContainsKey($Role)) {
        return [string]$models.ByRole[$Role]
    }
    if ($Tier -eq 'fast' -and $models.ContainsKey('Fast') -and $models.Fast) { return [string]$models.Fast }
    if ($Tier -eq 'strong' -and $models.ContainsKey('Strong') -and $models.Strong) { return [string]$models.Strong }
    if ($models.ContainsKey('Default') -and $models.Default) { return [string]$models.Default }
    return [string]$cfg.Model
}
