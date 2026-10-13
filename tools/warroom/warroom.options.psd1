# warroom.options.psd1 — konfigurasi War Room (editable).
# Nilai bawaan adalah KEBIJAKAN, bukan bukti pengeluaran.
# Tarif token: harga resmi DeepSeek per 2026-10-11 (unit USD per 1 juta token).
#   Sumber: https://api-docs.deepseek.com/quick_start/pricing
#   Mode PEAK dipakai untuk reservasi konservatif (off-peak = setengah peak).
# Kurs USD->IDR WAJIB disesuaikan pengguna; tandai tanggal verifikasi.
@{
    Model = 'deepseek/deepseek-flash'

    Agents = @{
        Lead     = 'lead-engineer'
        Code     = 'code-engineer'
        Quant    = 'quant-analyst'
        QA       = 'qa-engineer'
        Reviewer = 'reviewer'
        Security = 'security-engineer'
        UIUX     = 'uiux-designer'
        Tech     = 'technical-analyst'
        Fundamental = 'fundamental-analyst'
        SEO      = 'seo-engineer'
    }

    MonthlyBudgetIDR          = 50000
    TargetAutomationBudgetIDR = 35000
    WarningThresholdIDR       = 25000
    ReducedModeThresholdIDR   = 30000
    HardPauseThresholdIDR     = 35000
    PerCycleBudgetIDR         = 1000
    MaxCyclesPerDay           = 0       # 0 = TANPA batas siklus harian
    MaxDiscussionRounds       = 2
    MaxConcurrentModelTasks   = 2
    MaxRepairAttempts         = 2
    MaxOutputTokensPerCall    = 4096
    NormalIdleIntervalMinutes = 30
    FailureBackoffMinutes     = 60

    # --- Routing model & efisiensi konteks (pintar + irit) ---
    # Model KUAT hanya untuk tugas kritis (rencana, implementasi, verifikasi);
    # model FLASH murah untuk investigasi/reaksi/rapat. Ganti ID bila perlu.
    Models                    = @{
        Default = 'deepseek/deepseek-flash'     # fallback semua peran
        Fast    = 'deepseek/deepseek-flash'     # tugas ringan: investigasi, reaksi, rapat
        Strong  = 'deepseek/deepseek-v4-pro'    # tugas kritis: rencana, implementasi, verifikasi
        ByRole  = @{                            # override per-peran (opsional)
            'lead-plan'       = 'deepseek/deepseek-v4-pro'
            'code-implement'  = 'deepseek/deepseek-v4-pro'
            'reviewer-verify' = 'deepseek/deepseek-v4-pro'
        }
        ByAgent = @{}                           # mis. @{ 'code-engineer' = 'deepseek/deepseek-v4-pro' }
    }
    EnableCrossTalk           = $true   # reaksi silang antar-investigator (matikan utk hemat)
    MaxAgentRetries           = 1       # ulangan otomatis saat agen gagal (transient), bukan saat anggaran ditolak
    PlanMaxChars              = 6000    # batas panjang rencana yang diteruskan antar-tahap
    FindingsMaxChars          = 8000    # batas panjang temuan yang diteruskan
    ReactionsMaxChars         = 3000    # batas panjang reaksi silang
    RepoMapMaxChars           = 6000    # batas peta repo yang disuntik ke prompt

    # --- Memori pembelajaran (loop refleksi: agen makin pintar tiap siklus) ---
    # Pelajaran tiap siklus disaring ke state/learning/<agen>.md lalu disuntik ke
    # prompt berikutnya. Deterministik, tanpa panggilan model tambahan.
    EnableLearning            = $true   # matikan untuk hemat konteks
    LearningMaxEntries        = 40      # jumlah entri pelajaran per agen (terbaru menang)
    LearningMemoryMaxChars    = 2500    # batas memori yang disuntik ke prompt
    LearningSimilarityThreshold = 0.75  # ambang Jaccard: pelajaran mirip digabung (mengerucut)
    LearningMergeThreshold    = 0.5     # ambang aglomeratif saat memori penuh (makin mengerucut)
    LearningRetrievalTopK     = 6       # hanya TopK pelajaran paling RELEVAN yang disuntik (irit)
    LearningHistoryMaxEntries = 30      # jumlah tugas lama yang diingat
    LearningHistoryMaxChars   = 1200    # batas riwayat tugas yang disuntik ke prompt
    # Saat anggaran warning/reduced, suntikan memori & riwayat menyusut otomatis
    # (thrift) agar tetap irit token.

    # --- Mode batch manual (tanpa VPS) ---
    # Sekali jalankan Invoke-AutonomousLoop.ps1: N siklus, lalu berhenti.
    CyclesPerRun              = 4       # 0 = TANPA batas siklus per run (dibatasi MaxRunMinutes)
    MaxRunMinutes             = 180     # batas wall-clock per run (3 jam)
    InterCycleDelaySeconds    = 20      # jeda pendek antar siklus
    ExecuteByDefault          = $true   # run biasa = eksekusi nyata; pakai -DryRun untuk aman

    # --- Publikasi otonom (commit + push -> deploy Render) ---
    # Staging dibatasi ke jalur pengembangan; file pribadi pengguna tidak disentuh.
    # AutoPush = $true -> saklar utama: setelah run selesai otomatis commit + push origin
    #   (memicu deploy). AutoCommit saja = commit lokal tanpa push.
    AutoCommit                = $true
    AutoPush                  = $true
    PublishPaths              = @('.opencode', 'tools', 'routes', 'tests', 'api', 'pine', 'templates', 'static')

    UsdToIdr                  = 16000
    ExchangeRateVerifiedDate  = 'unverified-edit-me'
    PriceVerifiedDate         = '2026-10-11'

    # Tarif peak (konservatif). off-peak = /2 untuk flash.
    # CATATAN: tarif model 'opencode/*' di bawah adalah PLACEHOLDER konservatif;
    # verifikasi harga resmi lalu perbarui (biaya aktual tetap diambil dari laporan
    # provider bila tersedia). Model tanpa entri memakai DefaultRate.
    Rates = @{
        'deepseek/deepseek-flash' = @{
            InputCacheHitPerMillionUSD  = 0.006
            InputCacheMissPerMillionUSD = 0.30
            OutputPerMillionUSD         = 1.20
        }
        'deepseek/deepseek-v4-pro' = @{
            InputCacheHitPerMillionUSD  = 0.044
            InputCacheMissPerMillionUSD = 1.32
            OutputPerMillionUSD         = 3.96
        }
        'opencode/gemini-3.8-flash' = @{
            InputCacheHitPerMillionUSD  = 0.03
            InputCacheMissPerMillionUSD = 0.50
            OutputPerMillionUSD         = 1.50
        }
        'opencode/claude-fable-5-1' = @{
            InputCacheHitPerMillionUSD  = 0.30
            InputCacheMissPerMillionUSD = 3.00
            OutputPerMillionUSD         = 15.00
        }
    }

    DefaultRate = @{
        InputCacheHitPerMillionUSD  = 0.006
        InputCacheMissPerMillionUSD = 0.30
        OutputPerMillionUSD         = 1.20
    }
}
