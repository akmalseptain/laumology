# lib/LearningManager.ps1 — memori pembelajaran agen (loop refleksi yang MENGERUCUT).
# Tiap siklus menyaring pelajaran nyata (kegagalan gate, verifikasi menolak,
# pendekatan yang berhasil) ke berkas state/learning/<agen>.md lalu
# menyuntikkannya kembali ke prompt siklus berikutnya. Deterministik & tanpa
# panggilan model tambahan (hemat biaya).
#
# Prinsip:
#  - MENGERUCUT: pelajaran yang mirip digabung (Jaccard) menjadi satu entri
#    kanonik dengan hitungan (xN); memori jadi padat, bukan menumpuk.
#  - IRIT TOKEN: hanya sinyal terpenting yang disuntik + ukuran menyusut otomatis
#    saat anggaran memasuki mode warning/reduced (thrift).
#  - RIWAYAT TUGAS: tugas lama dicatat ringkas agar agen tidak mengulang pekerjaan.
# Bergantung: Common.ps1, ModelRouter.ps1, BudgetManager.ps1 (untuk thrift).

function Get-LearningDir {
    $d = Join-Path (Get-WarRoomStateDir) 'learning'
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    return $d
}

function ConvertTo-SafeLearningName {
    # Nama berkas aman; agen kosong = memori global.
    param([string]$Agent)
    $n = if ([string]::IsNullOrWhiteSpace($Agent)) { 'global' } else { $Agent }
    return ($n -replace '[^A-Za-z0-9._-]', '_')
}

function Get-AgentMemoryPath {
    param([string]$Agent)
    return (Join-Path (Get-LearningDir) ((ConvertTo-SafeLearningName $Agent) + '.md'))
}

function Get-LearningHistoryPath {
    return (Join-Path (Get-LearningDir) 'history.md')
}

function Get-LessonKey {
    # Kunci dedup persis: normalisasi spasi/kapital.
    param([string]$Lesson)
    if ([string]::IsNullOrEmpty($Lesson)) { return '' }
    return (($Lesson -replace '\s+', ' ').Trim().ToLowerInvariant())
}

$script:WarRoomLessonStopwords = @(
    'yang', 'dan', 'atau', 'di', 'ke', 'dari', 'untuk', 'pada', 'dengan', 'adalah',
    'ini', 'itu', 'the', 'a', 'an', 'of', 'to', 'in', 'is', 'are', 'was', 'for',
    'gate', 'gagal', 'verifikasi', 'pelajaran', 'catatan', 'modul'
)

function Get-LessonTokens {
    # Token bermakna (>=3 huruf, tanpa kata umum) untuk mengukur kemiripan.
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return @() }
    $toks = @($Text.ToLowerInvariant() -split '[^a-z0-9_\.]+' |
        Where-Object { $_.Length -ge 3 -and ($script:WarRoomLessonStopwords -notcontains $_) })
    return $toks
}

function Get-LessonSimilarity {
    # Jaccard atas himpunan token: 0..1 (makin tinggi makin mirip).
    param([string]$A, [string]$B)
    if ($null -eq $A -or $null -eq $B) { return 0.0 }
    $ka = Get-LessonKey $A
    $kb = Get-LessonKey $B
    if ($ka -and $ka -eq $kb) { return 1.0 }
    $ta = @(Get-LessonTokens $A); $tb = @(Get-LessonTokens $B)
    if ($ta.Count -eq 0 -or $tb.Count -eq 0) { return 0.0 }
    $setA = @{}
    foreach ($t in $ta) { $setA[$t] = $true }
    $common = @{}
    foreach ($t in $tb) { if ($setA.ContainsKey($t)) { $common[$t] = $true } }
    if ($common.Count -eq 0) { return 0.0 }
    $union = $setA.Count
    foreach ($t in $tb) { if (-not $setA.ContainsKey($t)) { $union++ } }
    if ($union -le 0) { return 0.0 }
    return [math]::Round($common.Count / $union, 3)
}

function Get-LearningThriftFactor {
    # Faktor pemangkasan memori: makin ketat anggaran, makin kecil suntikan.
    try {
        $m = (Get-BudgetStatus).mode
        switch ($m) {
            'reduced' { return 0.5 }
            'warning' { return 0.75 }
            'paused'  { return 0.3 }
            default   { return 1.0 }
        }
    } catch { return 1.0 }
}

function Merge-SimilarEntries {
    # MENGERUCUT agresif (aglomeratif): selama jumlah melebihi batas, gabungkan
    # pasangan paling mirip (>= Threshold, hitungan dijumlahkan, teks terpendek
    # dipertahankan sebagai inti). Bila tak ada yang cukup mirip, buang entri
    # ber-hitungan terendah (tertua sebagai tie-break).
    param([object[]]$Entries, [int]$Max, [double]$Threshold)
    if ($Max -lt 1) { $Max = 1 }
    $list = New-Object System.Collections.ArrayList
    foreach ($e in @($Entries)) { [void]$list.Add($e) }
    while ($list.Count -gt $Max) {
        $bestI = -1; $bestJ = -1; $bestSim = 0.0
        for ($i = 0; $i -lt $list.Count; $i++) {
            for ($j = $i + 1; $j -lt $list.Count; $j++) {
                $sim = Get-LessonSimilarity $list[$i].text $list[$j].text
                if ($sim -gt $bestSim) { $bestSim = $sim; $bestI = $i; $bestJ = $j }
            }
        }
        if ($bestI -ge 0 -and $bestSim -ge $Threshold) {
            $a = $list[$bestI]; $b = $list[$bestJ]
            $a.count = [int]$a.count + [int]$b.count
            if ($b.text.Length -lt $a.text.Length) { $a.text = $b.text; $a.key = (Get-LessonKey $b.text) }
            $list.RemoveAt($bestJ)
        } else {
            $vi = 0; $vc = [int]$list[0].count; $vo = [int]$list[0].order
            for ($i = 1; $i -lt $list.Count; $i++) {
                $c = [int]$list[$i].count; $o = [int]$list[$i].order
                if ($c -lt $vc -or ($c -eq $vc -and $o -lt $vo)) { $vc = $c; $vo = $o; $vi = $i }
            }
            $list.RemoveAt($vi)
        }
    }
    $k = 0
    foreach ($e in $list) { $e.order = $k; $k++ }
    return @($list)
}

function Read-AgentLessonEntries {
    # Baca berkas memori -> array entri { count, text, key, order }.
    param([string]$Agent)
    $path = Get-AgentMemoryPath -Agent $Agent
    $entries = @()
    if (-not (Test-Path -LiteralPath $path)) { return $entries }
    $order = 0
    foreach ($ln in (Get-Content -LiteralPath $path -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if ($ln -match '^\s*-\s+(.*?)(?:\s+\(x(\d+)\))?\s*$') {
            $t = $Matches[1].Trim()
            if (-not $t) { continue }
            $c = if ($Matches[2]) { [int]$Matches[2] } else { 1 }
            $entries += [pscustomobject]@{ count = $c; text = $t; key = (Get-LessonKey $t); order = $order }
            $order++
        }
    }
    return $entries
}

function Write-AgentLessonEntries {
    param([string]$Agent, [object[]]$Entries)
    $path = Get-AgentMemoryPath -Agent $Agent
    $out = @(
        ('# Memori pembelajaran agen: ' + (ConvertTo-SafeLearningName $Agent)),
        ('<!-- diperbarui otomatis oleh War Room; ' + (Get-WarRoomUtcNow) + ' -->'),
        ''
    )
    foreach ($e in @($Entries)) {
        $suffix = if ([int]$e.count -gt 1) { ' (x' + [int]$e.count + ')' } else { '' }
        $out += ('- {0}{1}' -f $e.text, $suffix)
    }
    Set-Content -LiteralPath $path -Value ($out -join "`n") -Encoding UTF8
    return $path
}

function Add-AgentLesson {
    # Tambah pelajaran dengan MENGERUCUT:
    #  - mirip entri lama (Jaccard >= LearningSimilarityThreshold) -> gabung (hitungan++)
    #  - baru -> tambah di akhir
    #  - bila melebihi LearningMaxEntries -> buang entri ber-hitungan terendah (tertua
    #    sebagai tie-break) supaya yang padat/berulang bertahan.
    param(
        [string]$Agent = 'global',
        [Parameter(Mandatory)][string]$Lesson,
        [string]$CycleId = ''
    )
    $tuning = Get-WarRoomTuning
    if (-not $tuning.EnableLearning) { return $null }
    $text = (ConvertTo-WarRoomPlainText $Lesson) -replace '\s+', ' '
    $text = $text.Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    if ($text.Length -gt 240) { $text = $text.Substring(0, 240).Trim() }
    $key = Get-LessonKey $text
    if (-not $key) { return $null }
    $path = Get-AgentMemoryPath -Agent $Agent
    $max = [int]$tuning.LearningMaxEntries
    if ($max -lt 5) { $max = 5 }
    $threshold = [double]$tuning.LearningSimilarityThreshold
    if ($threshold -le 0 -or $threshold -gt 1) { $threshold = 0.75 }

    Invoke-WithFileLock -LockPath ($path + '.lock') -Script {
        $entries = @(Read-AgentLessonEntries -Agent $Agent)
        $best = $null
        $bestSim = 0.0
        foreach ($e in $entries) {
            if ($e.key -eq $key) { $best = $e; $bestSim = 1.0; break }
            $sim = Get-LessonSimilarity $e.text $text
            if ($sim -ge $threshold -and $sim -gt $bestSim) { $best = $e; $bestSim = $sim }
        }
        if ($best) {
            $best.count = [int]$best.count + 1
        } else {
            $entries += [pscustomobject]@{ count = 1; text = $text; key = $key; order = $entries.Count }
        }
        if ($entries.Count -gt $max) {
            $mergeT = [double]$tuning.LearningMergeThreshold
            if ($mergeT -le 0 -or $mergeT -gt 1) { $mergeT = 0.5 }
            $entries = @(Merge-SimilarEntries -Entries $entries -Max $max -Threshold $mergeT)
        }
        Write-AgentLessonEntries -Agent $Agent -Entries $entries | Out-Null
        return $entries.Count
    } | Out-Null
    return $text
}

function Get-AgentMemory {
    # Ambil pelajaran PALING RELEVAN (retrieval) ber-signal tinggi untuk disuntik.
    # Query (mis. target/rencana) membuat hanya pelajaran terkait yang dikirim ->
    # lebih cerdas sekaligus lebih irit token.
    param([string]$Agent, [int]$MaxChars = 0, [int]$TopEntries = 12, [string]$Query = '')
    $entries = @(Read-AgentLessonEntries -Agent $Agent)
    if ($entries.Count -eq 0) { return '' }
    $sortSignal = { param($objs) @($objs | Sort-Object -Property `
        @{ Expression = { [int]$_.count }; Descending = $true }, `
        @{ Expression = { [int]$_.order }; Descending = $true }) }
    if ($Query -and $Query.Trim()) {
        $scored = @(foreach ($e in $entries) {
            $e | Add-Member -NotePropertyName _sim -NotePropertyValue (Get-LessonSimilarity $Query $e.text) -Force -PassThru
        })
        $picked = @($scored | Where-Object { [double]$_._sim -gt 0 } |
            Sort-Object -Property @{ Expression = { [double]$_._sim }; Descending = $true }, @{ Expression = { [int]$_.count }; Descending = $true })
        if ($picked.Count -eq 0) { $picked = @(& $sortSignal $entries) }
    } else {
        $picked = @(& $sortSignal $entries)
    }
    if ($TopEntries -gt 0 -and $picked.Count -gt $TopEntries) { $picked = @($picked[0..($TopEntries - 1)]) }
    $text = (($picked | ForEach-Object {
        if ([int]$_.count -gt 1) { '- {0} (x{1})' -f $_.text, [int]$_.count } else { '- ' + $_.text }
    }) -join "`n")
    if ($MaxChars -gt 0) { $text = Limit-WarRoomText -Text $text -MaxChars $MaxChars }
    return $text
}

function Get-LearningMemoryBlock {
    # Gabung memori agen + memori global menjadi satu blok teks untuk prompt.
    # Ukuran menyusut otomatis (thrift) saat anggaran menipis -> irit token.
    param([string[]]$Agents = @(), [int]$MaxChars = 0, [string]$Query = '')
    $tuning = Get-WarRoomTuning
    if (-not $tuning.EnableLearning) { return '' }
    if ($MaxChars -le 0) { $MaxChars = [int]$tuning.LearningMemoryMaxChars }
    $topK = [int]$tuning.LearningRetrievalTopK
    if ($topK -lt 3) { $topK = 3 }
    $parts = @()
    $seen = @{}
    foreach ($a in (@($Agents) + @('global'))) {
        $name = if ([string]::IsNullOrWhiteSpace($a)) { 'global' } else { $a }
        $safe = ConvertTo-SafeLearningName $name
        if ($seen.ContainsKey($safe)) { continue }
        $seen[$safe] = $true
        $m = Get-AgentMemory -Agent $name -TopEntries $topK -Query $Query
        if ($m) { $parts += ('[{0}]' -f $name + "`n" + $m) }
    }
    if ($parts.Count -eq 0) { return '' }
    $budget = [int]($MaxChars * (Get-LearningThriftFactor))
    if ($budget -lt 200) { $budget = 200 }
    return (Limit-WarRoomText -Text ($parts -join "`n") -MaxChars $budget)
}

function Add-WarRoomTaskHistory {
    # Catat tugas yang sudah dikerjakan (ringkas) agar tidak diulang siklus berikutnya.
    param(
        [string]$Title = '',
        [string]$Outcome = '',
        [string]$CycleId = ''
    )
    $tuning = Get-WarRoomTuning
    if (-not $tuning.EnableLearning) { return }
    $t = (ConvertTo-WarRoomPlainText $Title) -replace '\s+', ' '
    $t = $t.Trim()
    if ([string]::IsNullOrWhiteSpace($t)) { return }
    if ($t.Length -gt 160) { $t = $t.Substring(0, 160).Trim() }
    $o = if ([string]::IsNullOrWhiteSpace($Outcome)) { 'info' } else { $Outcome }
    $line = ('- [{0}] {1}: {2}' -f $o, (Get-Date).ToString('yyyy-MM-dd'), $t)
    $path = Get-LearningHistoryPath
    $max = [int]$tuning.LearningHistoryMaxEntries
    if ($max -lt 5) { $max = 5 }
    Invoke-WithFileLock -LockPath ($path + '.lock') -Script {
        $lines = @()
        if (Test-Path -LiteralPath $path) {
            $lines = @(Get-Content -LiteralPath $path -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*-\s+' })
        }
        if ($lines -notcontains $line) { $lines += $line }
        if ($lines.Count -gt $max) { $lines = $lines[($lines.Count - $max)..($lines.Count - 1)] }
        $out = @(
            '# Riwayat tugas War Room',
            ('<!-- diperbarui otomatis; ' + (Get-WarRoomUtcNow) + ' -->'),
            ''
        ) + $lines
        Set-Content -LiteralPath $path -Value ($out -join "`n") -Encoding UTF8
    } | Out-Null
}

function Get-WarRoomTaskHistoryBlock {
    # Blok riwayat tugas (ringkas) untuk orientasi Lead; menyusut saat anggaran menipis.
    param([int]$MaxChars = 0, [int]$TopEntries = 12)
    $tuning = Get-WarRoomTuning
    if (-not $tuning.EnableLearning) { return '' }
    if ($MaxChars -le 0) { $MaxChars = [int]$tuning.LearningHistoryMaxChars }
    $path = Get-LearningHistoryPath
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    $lines = @(Get-Content -LiteralPath $path -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*-\s+' })
    if ($lines.Count -eq 0) { return '' }
    if ($TopEntries -gt 0 -and $lines.Count -gt $TopEntries) { $lines = $lines[($lines.Count - $TopEntries)..($lines.Count - 1)] }
    $budget = [int]($MaxChars * (Get-LearningThriftFactor))
    if ($budget -lt 150) { $budget = 150 }
    # Pertahankan entri TERBARU yang muat anggaran (buang yang tertua lebih dulu).
    $acc = @()
    $len = 0
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $line = $lines[$i]
        if ($acc.Count -gt 0 -and ($len + $line.Length + 1) -gt $budget) { break }
        $acc = @($line) + $acc
        $len += $line.Length + 1
    }
    return ($acc -join "`n")
}

function Update-WarRoomLearning {
    # Loop refleksi deterministik: dari sinyal siklus -> pelajaran per agen + global.
    # Semua argumen opsional; hanya sinyal yang tersedia yang dipakai.
    param(
        [string]$CycleId = '',
        [int]$GateExit = -1,
        [string]$GateTail = '',
        [string]$Recommendation = '',
        [string]$Target = '',
        [string]$VerifyText = ''
    )
    $tuning = Get-WarRoomTuning
    if (-not $tuning.EnableLearning) { return }
    $cfg = Get-WarRoomConfig
    $codeAgent = $cfg.Agents.Code
    $leadAgent = $cfg.Agents.Lead

    # 1) Kegagalan gate = pelajaran kuat untuk penulis kode + pengetahuan global.
    if ($GateExit -gt 0 -and $GateTail) {
        $first = (($GateTail -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 1)
        $first = (ConvertTo-WarRoomPlainText $first).Trim()
        if ($first) {
            $lesson = ('Gate gagal ({0}): {1}' -f $CycleId, $first)
            Add-AgentLesson -Agent $codeAgent -Lesson $lesson -CycleId $CycleId | Out-Null
            Add-AgentLesson -Agent 'global' -Lesson $lesson -CycleId $CycleId | Out-Null
        }
    }

    # 2) Verifikasi menolak = pelajaran untuk penulis kode + global.
    if ($Recommendation -in @('REVISI', 'TOLAK')) {
        $reason = ''
        if ($VerifyText) {
            $cand = (($VerifyText -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 2) -join ' '
            $reason = (ConvertTo-WarRoomPlainText $cand).Trim()
        }
        if (-not $reason) { $reason = 'perlu revisi atas perubahan terakhir' }
        $lesson = ('Verifikasi {0} ({1}): {2}' -f $Recommendation, $CycleId, $reason)
        Add-AgentLesson -Agent $codeAgent -Lesson $lesson -CycleId $CycleId | Out-Null
        Add-AgentLesson -Agent 'global' -Lesson $lesson -CycleId $CycleId | Out-Null
    }

    # 3) Siklus sukses = memori positif untuk Lead (pendekatan yang berhasil).
    if ($Recommendation -eq 'TERIMA' -and $GateExit -eq 0 -and $Target) {
        $t = (ConvertTo-WarRoomPlainText $Target).Trim()
        if ($t.Length -gt 160) { $t = $t.Substring(0, 160).Trim() }
        if ($t) { Add-AgentLesson -Agent $leadAgent -Lesson ('Berhasil ({0}): {1}' -f $CycleId, $t) -CycleId $CycleId | Out-Null }
    }

    Write-WarRoomEvent -Category 'learning' -Message "pembelajaran diperbarui ($CycleId)" | Out-Null
}
