# lib/PipelineManager.ps1 — siklus rekayasa bertahap (multi-agen, 1 penulis, paralel read-only).
# Alur: PLAN (lead) -> INVESTIGATE (quant||qa, read-only) -> IMPLEMENT (code, 1 penulis)
#       -> VERIFY (quant||reviewer, read-only). Semua panggilan lewat kendali anggaran.

function Invoke-WarRoomPipeline {
    param(
        [Parameter(Mandatory)][string]$CycleId,
        $Item = $null,
        [string]$ExtraContext = '',
        [int]$TimeoutSec = 900,
        [switch]$Auto,
        [int]$MaxConcurrent = 0
    )
    $cfg = Get-WarRoomConfig
    $lead = $cfg.Agents.Lead
    $code = $cfg.Agents.Code
    $quant = $cfg.Agents.Quant
    $qa = $cfg.Agents.QA
    $reviewer = $cfg.Agents.Reviewer
    $security = if ($cfg.Agents.ContainsKey('Security')) { $cfg.Agents.Security } else { '' }
    $uiux = if ($cfg.Agents.ContainsKey('UIUX')) { $cfg.Agents.UIUX } else { '' }
    $tech = if ($cfg.Agents.ContainsKey('Tech')) { $cfg.Agents.Tech } else { '' }
    $tuning = Get-WarRoomTuning
    if ($MaxConcurrent -le 0) { $MaxConcurrent = [int]$cfg.MaxConcurrentModelTasks }
    # Mode anggaran 'reduced': matikan paralelisme + cross-talk untuk menghemat biaya.
    $budgetMode = (Get-BudgetStatus).mode
    $allowCrossTalk = $tuning.EnableCrossTalk -and ($budgetMode -in @('normal', 'warning'))
    if ($budgetMode -eq 'reduced' -and $MaxConcurrent -gt 1) { $MaxConcurrent = 1 }

    if ($Item) {
        $target = "ITEM $($Item.id): $($Item.title)`nBUKTI: $($Item.evidence)`nBERKAS: $($Item.files -join ', ')`nKRITERIA: $($Item.acceptance)"
    } else {
        $target = "Tidak ada item backlog. Temukan SATU peningkatan kecil, aman, dan reversibel (berbasis bukti path:line)."
    }

    # Routing model: tugas kritis (plan/implement/verify) boleh ke model lebih kuat.
    $modelLead = Resolve-WarRoomModel -Agent $lead -Role 'lead-plan' -Tier 'strong'
    $modelCode = Resolve-WarRoomModel -Agent $code -Role 'code-implement' -Tier 'strong'
    $summary = [ordered]@{ plan = $false; investigate = 0; implement = $false; verify = 0; recommendation = '' }

    # --- 1. PLAN (Lead, tanpa mengubah berkas) ---
    $repoMap = ''
    try {
        $rmScript = Join-Path (Get-WarRoomRoot) 'tools\repomap.py'
        if (Test-Path -LiteralPath $rmScript) { $repoMap = ((& py -3.14 $rmScript 2>$null) -join "`n") }
    } catch { $repoMap = '' }
    $repoMap = Limit-WarRoomText $repoMap $tuning.RepoMapMaxChars
    $chaosStyle = "Perankan dirimu NATURAL seperti ngobrol di kantor: sapa rekan dengan nama depan, boleh nyela/bercanda/berdebat ringan, kadang melantur sedikit lalu balik fokus. Sesuaikan diksi dengan asal daerah (secukupnya; jangan berlebihan/menyinggung). WAJIB tetap akurat, sertakan bukti path:line, dan keputusan tegas. (Agama/keluarga hanya latar; JANGAN jadikan bahan lelucon sensitif.)"
    $planPrompt = @"
KARAKTER: $(Get-AgentPersona -Agent $lead)
$chaosStyle

Anda Lead Engineer War Room. Susun rencana implementasi TERFOKUS (maksimal SATU peningkatan).
JANGAN mengubah berkas apa pun; hanya analisis & rencana.
Ikuti AGENTS.md (jangan ubah rumus keuangan tanpa bukti, jaga uji golden).
Ringkas (<= 12 baris).

$target
KONTEKS: $ExtraContext

PETA REPO (ringkas, untuk orientasi):
$repoMap

Keluarkan: (a) masalah & bukti path:line, (b) langkah implementasi, (c) berkas yang akan diubah, (d) kriteria penerimaan, (e) risiko regresi.
WAJIB tulis satu baris terakhir: PILIHAN_AGEN: a, b, c  -> pilih 1-3 spesialis PALING RELEVAN untuk tugas ini (pilihan: quant, qa, security, uiux, technical). Mereka akan menginvestigasi & memverifikasi.
"@
    Write-StageProgress -Stages @('PLAN', 'INVESTIGATE', 'IMPLEMENT', 'VERIFY') -Current 0 -Color 'Cyan'
    Write-Section -Title ("[1/4] PLAN  -  " + $lead) -Color 'Cyan'
    $plan = $null
    $planText = ''
    $attempt = 0
    while ($attempt -le $tuning.MaxAgentRetries) {
        $attempt++
        $plan = Invoke-OpenCodeAgentWithBudget -Agent $lead -Prompt $planPrompt -CycleId $CycleId -Role 'lead-plan' -Model $modelLead -TimeoutSec $TimeoutSec -Auto:$Auto -Stream
        $planText = if ($plan.allowed -and $plan.result) { $plan.result.text } else { '' }
        if ($planText) { break }
        # Ulangi hanya bila panggilan benar-benar gagal (bukan ditolak anggaran).
        $transient = $plan.allowed -and $plan.result -and $plan.result.exitCode -ne 0 -and -not $plan.result.timedOut
        if (-not $transient -or $attempt -gt $tuning.MaxAgentRetries) { break }
        Write-Host ("  [1/4] PLAN gagal, ulangi ({0}/{1})..." -f $attempt, $tuning.MaxAgentRetries) -ForegroundColor Yellow
    }
    $summary.plan = ($plan.allowed -and $plan.result -and $plan.result.exitCode -eq 0 -and [bool]$planText)
    Write-Host ("  [1/4] PLAN: {0}" -f $(if ($summary.plan) { 'ok' } else { 'gagal/ditolak' })) -ForegroundColor $(if ($summary.plan) { 'Green' } else { 'Yellow' })
    if ($plan.allowed -and $plan.result) { Write-AgentVoice -Agent $lead -Phase 'plan' -Text $planText }
    if ($summary.plan) { Invoke-WarRoomBeep -Kind 'info' }
    if (-not $planText) {
        # Bila perencanaan tak menghasilkan apa pun, hentikan pipeline lebih awal.
        # Tetap tulis notulen siklus ini agar 'replay' tidak menampilkan rapat lama
        # (dulu siklus gagal tak menyimpan apa pun sehingga replay terlihat "nyangkut").
        $reason = if (-not $plan.allowed) { "anggaran: $($plan.reason)" }
            elseif ($plan.result -and $plan.result.exitCode -ne 0) { "agen gagal (exit=$($plan.result.exitCode))" }
            else { 'rencana kosong' }
        $failMessages = @([pscustomobject]@{
            agent = $lead
            text  = "Tidak ada rencana yang dihasilkan ($reason). Siklus ini tidak menghasilkan rapat/implementasi."
        })
        Out-WarRoomMinutes -Title ("Siklus $CycleId") -Messages $failMessages -Decision 'TIDAK ADA RENCANA' -Id $CycleId | Out-Null
        Write-WarRoomEvent -Category 'orchestrator' -Level 'warn' -Message "pipeline $CycleId berhenti awal: $reason" | Out-Null
        return [pscustomobject]$summary
    }
    $planCtx = Limit-WarRoomText $planText $tuning.PlanMaxChars

    # --- 2. INVESTIGATE (paralel, read-only) - agen ditentukan LEAD ---
    $specMap = @{}
    foreach ($pair in @(
            @('quant', $quant), @('keuangan', $quant), @('finance', $quant), @('rumus', $quant), @('ml', $quant), @('kalibrasi', $quant),
            @('qa', $qa), @('api', $qa), @('kode', $qa), @('backend', $qa), @('test', $qa), @('uji', $qa),
            @('security', $security), @('keamanan', $security), @('input', $security), @('auth', $security),
            @('ui', $uiux), @('ux', $uiux), @('tampilan', $uiux), @('frontend', $uiux), @('desain', $uiux), @('aksesibilitas', $uiux),
            @('technical', $tech), @('ta', $tech), @('teknikal', $tech), @('chart', $tech), @('indikator', $tech), @('price', $tech)
        )) { $specMap[$pair[0]] = $pair[1] }
    $picked = @()
    if ($planText -match '(?im)^\s*PILIHAN_AGEN\s*:\s*(.+)$') {
        foreach ($tok in ($Matches[1] -split '[,\s]+')) {
            $k = $tok.Trim().ToLowerInvariant()
            if ($k -and $specMap.ContainsKey($k) -and $specMap[$k] -and ($picked -notcontains $specMap[$k])) { $picked += $specMap[$k] }
        }
    }
    if ($picked.Count -eq 0) { $picked = @($quant, $qa) }
    $investAgents = @($picked)
    Write-Host ("  Lead memilih agen: " + ($investAgents -join ', ')) -ForegroundColor DarkGray
    Write-Section -Title ("[2/4] INVESTIGATE  -  " + ($investAgents -join ' | ')) -Color 'Magenta'
    $runs = @()
    foreach ($ag in $investAgents) {
        $modelInvest = Resolve-WarRoomModel -Agent $ag -Role "$ag-investigate" -Tier 'fast'
        $investPrompt = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
$chaosStyle

Anda agen '$ag'. Investigasi READ-ONLY terkait rencana berikut. JANGAN mengubah berkas.
WAJIB sertakan bukti path:line dan risiko nyata. Ringkas (<= 10 baris).

RENCANA LEAD:
$planCtx
"@
        $runs += Start-WarRoomAgentProcess -Agent $ag -Prompt $investPrompt -CycleId $CycleId -Role "$ag-investigate" -Model $modelInvest -TimeoutSec $TimeoutSec -Auto:$Auto
    }
    $inv = Wait-WarRoomProcessesStreaming -Runs $runs -Phase 'investigate' -TimeoutSec ($TimeoutSec + 120)
    $findings = ($inv | ForEach-Object {
        $t = if ($_.result) { $_.result.text } else { '' }
        "[$($_.agent)]`n$t"
    }) -join "`n`n"
    $findings = Limit-WarRoomText $findings $tuning.FindingsMaxChars
    $summary.investigate = @($inv | Where-Object { $_.result -and $_.result.ok }).Count
    Write-Host ("  [2/4] INVESTIGATE: {0}/{1} agen ok" -f $summary.investigate, $investAgents.Count) -ForegroundColor Cyan

    # REAKSI silang (semi-chaos): tiap investigator menanggapi temuan rekan.
    # Dimatikan saat EnableCrossTalk=false atau anggaran mode reduced (hemat biaya).
    $reactions = ''
    if ($allowCrossTalk -and $investAgents.Count -gt 1 -and $findings) {
        Write-Section -Title "[2b/4] REAKSI silang-cakap" -Color 'Magenta'
        $rruns = @()
        foreach ($ag in $investAgents) {
            $modelReact = Resolve-WarRoomModel -Agent $ag -Role "$ag-react" -Tier 'fast'
            $rp = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
Gaya: ngobrol natural, boleh nyindir/bercanda ringan, tapi tetap berbukti.

Ini temuan rekan-rekanmu:
$findings

Reaksi SINGKAT (1-2 kalimat, in-character): setuju atau keberatan? Alasan singkat.
"@
            $rruns += Start-WarRoomAgentProcess -Agent $ag -Prompt $rp -CycleId $CycleId -Role "$ag-react" -Model $modelReact -TimeoutSec $TimeoutSec -Auto:$Auto
        }
        $react = Wait-WarRoomProcessesStreaming -Runs $rruns -Phase 'reaksi' -TimeoutSec ($TimeoutSec + 120)
        $reactions = ($react | ForEach-Object { "[$($_.agent)] " + $(if ($_.result) { $_.result.text } else { '' }) }) -join "`n"
        $reactions = Limit-WarRoomText $reactions $tuning.ReactionsMaxChars
    }

    # --- 3. IMPLEMENT (Code Engineer, satu penulis) ---
    $implPrompt = @"
KARAKTER: $(Get-AgentPersona -Agent $code)
$chaosStyle

Anda Code Engineer War Room. Implementasikan rencana berikut secara TERFOKUS (satu peningkatan).
Ikuti AGENTS.md (bahasa Indonesia; jangan ubah rumus keuangan tanpa fixture; jaga uji golden).
Jangan commit/push. Jangan operasi Git destruktif.
Sebut berkas yang diubah + ringkasan secara natural.

RENCANA:
$planCtx

TEMUAN INVESTIGASI:
$findings

REAKSI TIM (silang-cakap):
$reactions

Setelah selesai: jalankan 'py -3.14 tools/quality_gate.py' dan laporkan hasil nyatanya.
"@
    Write-StageProgress -Stages @('PLAN', 'INVESTIGATE', 'IMPLEMENT', 'VERIFY') -Current 2 -Color 'Green'
    Write-Section -Title ("[3/4] IMPLEMENT  -  " + $code) -Color 'Green'
    $impl = Invoke-OpenCodeAgentWithBudget -Agent $code -Prompt $implPrompt -CycleId $CycleId -Role 'code-implement' -Model $modelCode -TimeoutSec $TimeoutSec -Auto:$Auto -Stream
    $summary.implement = ($impl.allowed -and $impl.result -and $impl.result.exitCode -eq 0)
    Write-Host ("  [3/4] IMPLEMENT: {0}" -f $(if ($summary.implement) { 'ok' } else { 'gagal/ditolak' })) -ForegroundColor $(if ($summary.implement) { 'Green' } else { 'Yellow' })
    if ($impl.allowed -and $impl.result) { Write-AgentVoice -Agent $code -Phase 'implement' -Text $impl.result.text }
    Invoke-WarRoomBeep -Kind 'info'

    # --- 4. VERIFY (quant & reviewer paralel, read-only) ---
    $verifyAgents = @($reviewer)
    foreach ($a in $picked) { if ($a -and ($verifyAgents -notcontains $a)) { $verifyAgents += $a } }
    Write-Section -Title ("[4/4] VERIFY  -  " + ($verifyAgents -join ' | ')) -Color 'Blue'
    $vruns = @()
    foreach ($ag in $verifyAgents) {
        $tier = if ($ag -eq $reviewer) { 'strong' } else { 'fast' }
        $modelVerify = Resolve-WarRoomModel -Agent $ag -Role "$ag-verify" -Tier $tier
        $verifyPrompt = @"
KARAKTER: $(Get-AgentPersona -Agent $ag)
$chaosStyle

Anda agen '$ag'. Tinjau perubahan BELUM di-commit ('git --no-pager diff') terhadap rencana berikut. READ-ONLY.
Cari regresi, masalah keamanan, klaim tanpa bukti, atau penyimpangan dari rencana. Ringkas (<= 10 baris).
Akhiri dengan satu baris: REKOMENDASI: TERIMA atau REVISI.

RENCANA:
$planCtx
"@
        $vruns += Start-WarRoomAgentProcess -Agent $ag -Prompt $verifyPrompt -CycleId $CycleId -Role "$ag-verify" -Model $modelVerify -TimeoutSec $TimeoutSec -Auto:$Auto
    }
    $ver = Wait-WarRoomProcessesStreaming -Runs $vruns -Phase 'verify' -TimeoutSec ($TimeoutSec + 120)
    $summary.verify = @($ver | Where-Object { $_.result -and $_.result.ok }).Count
    foreach ($v in $ver) {
        if ($v.result -and $v.result.text -match 'REKOMENDASI:\s*(TERIMA|REVISI|TOLAK)') {
            $summary.recommendation = $Matches[1]
        }
    }
    Write-Host ("  [4/4] VERIFY: {0}/2 agen ok, rekomendasi={1}" -f $summary.verify, $summary.recommendation) -ForegroundColor Cyan

    $rec = [ordered]@{
        cycleId = $CycleId
        target = $target
        summary = $summary
        plan = $planText
        findings = $findings
        verify = ($ver | ForEach-Object { "[$($_.agent)] rekomendasi=$($_.result.recommendation)" })
        at = Get-WarRoomUtcNow
    }
    $file = Join-Path (Get-WarRoomStateDir) ("pipeline-{0}.json" -f $CycleId)
    Write-WarRoomJsonFile -Path $file -Object $rec
    Write-WarRoomEvent -Category 'orchestrator' -Message "pipeline $CycleId selesai; rekomendasi=$($summary.recommendation)" | Out-Null

    Invoke-WarRoomBeep -Kind $(if ($summary.recommendation -eq 'TERIMA') { 'ok' } else { 'warn' })
    $minutes = @()
    if ($planText) { $minutes += [pscustomobject]@{ agent = $lead; text = $planText } }
    foreach ($x in (@($inv) + @($ver))) { if ($x -and $x.result) { $minutes += [pscustomobject]@{ agent = $x.agent; text = $x.result.text } } }
    Out-WarRoomMinutes -Title ("Siklus $CycleId") -Messages $minutes -Decision $summary.recommendation -Id $CycleId | Out-Null
    Send-WarRoomToast -Title 'LAUMOLOGY War Room' -Text ("Siklus $CycleId selesai - rekomendasi: $($summary.recommendation)") | Out-Null

    return [pscustomobject]$summary
}
