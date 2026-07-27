# AelfLab Hub

Dashboard homelab pribadi. Satu proses FastAPI di port **8081** melayani tiga aplikasi, dibedakan lewat subdomain.

| Subdomain | Frontend | Router backend |
|---|---|---|
| `hub.aelflab.com` | `index.html` | `backend/main.py` — monitoring & cron |
| `finance.aelflab.com` | `finance.html` | `backend/finance.py` → `/api/finance/*` |
| `pdf.aelflab.com` | `pdf.html` | `backend/pdf/main.py` → `/api/pdf/*` |

Routing dilakukan dengan membaca header `Host`:

```python
@app.get("/")
async def serve_index(request: Request = None):
    host = request.headers.get("host", "") if request else ""
    if host.startswith("finance"): return FileResponse(HUB_DIR / "finance.html")
    if host.startswith("pdf"):     return FileResponse(HUB_DIR / "pdf.html")
    return FileResponse(HUB_DIR / "index.html")
```

Path `/finance` dan `/pdf` juga tersedia sebagai alternatif kalau diakses langsung lewat IP atau localhost.

`redirect.py` berjalan terpisah di port **8082** dan melakukan 301 dari `aelflab.com` ke `hub.aelflab.com`.

---

## Aplikasi

### 1. Hub — monitoring

Metrik diambil dengan memanggil `powershell.exe`, jadi **backend ini hanya jalan di Windows**:

- Disk D:, RAM (`Win32_OperatingSystem`), uptime (`LastBootUpTime`)
- GPU via performance counter (`gpu-perf.ps1`, `gpu.ps1`, `gpu-detail.ps1`)
- Traffic NIC (`network.ps1`), IP Tailscale + Ethernet
- Container Docker (`docker ps`), model Ollama (`ollama list` / `ollama ps`)
- Saldo DeepSeek lewat API
- History 30 hari (JSONL, snapshot per jam saat `/api/status` diakses)
- Speedtest (ping + curl) dan quick action

**Cron Manager** membaca `jobs.json` dan `executions.db` milik Hermes di `$HERMES_HOME/cron`, dan bisa memicu job manual lewat `hermes_cli.main cron run`. Hasilnya dikirim ke Telegram.

### 2. Finance

SQLite di `data/finance.db` dengan tabel `accounts`, `categories`, `transactions`, `budgets`, `recurring`, `installments`, `investments`. Saldo akun ter-update otomatis saat transaksi masuk. Harga BTC/ETH diambil dari CoinGecko dan emas dari harga-emas.org. Export Excel ber-styling via openpyxl.

Kategori dan akun default di-seed saat `GET /api/finance/init`.

Transaksi bisa diedit dan dihapus; efeknya ke saldo akun dibalik lewat satu fungsi (`_apply_balance`) sehingga saldo tidak pernah lepas sinkron. `POST /api/finance/recalc` menghitung ulang seluruh saldo dari daftar transaksi sebagai jaring pengaman.

Transaksi rutin (gaji, sewa, nafkah) menyimpan tanggal jatuh tempo berikutnya. `POST /api/finance/recurring/run-due` mencatat semua yang sudah jatuh tempo, termasuk yang tertunggak beberapa bulan, dan idempoten — dipanggil dua kali tidak membuat duplikat.

Budget `spent` selalu dihitung dari transaksi sebenarnya, bukan ditambah inkremental, jadi tetap benar walau budget dibuat setelah pengeluaran terjadi.

### 3. PDF Editor

Merge, split, extract text, info/metadata, tanda tangan, censor, watermark, deteksi stempel, dan preview halaman.

Tanda tangan bisa **ditulis langsung di browser** (canvas dengan pointer events, latar transparan, dipotong otomatis ke bounding box tinta) atau diunggah sebagai PNG/JPG.

Semua geometri memakai satu kontrak: **PDF point** (72/inch), origin kiri-atas — sama seperti ruang koordinat PyMuPDF. Preview dirender pada `dpi = 72 * zoom`, jadi:

```
canvas_px = pdf_pt * zoom
```

Setiap respons `GET /api/pdf/preview/{file}` membawa header geometri yang dipakai klien untuk konversi, sehingga nilainya tidak perlu ditebak:

| Header | Arti |
|---|---|
| `X-Pdf-Zoom` | zoom efektif yang benar-benar dipakai (bisa ter-clamp) |
| `X-Pdf-Page` | index halaman (0-based) yang dirender |
| `X-Pdf-Total-Pages` | jumlah halaman dokumen |
| `X-Pdf-Width-Pt` / `X-Pdf-Height-Pt` | dimensi halaman dalam point |

File hasil di `data/output/` juga bisa dijadikan input, jadi operasi bisa dirantai: sign → censor → watermark.

---

## Menjalankan

```bat
python -m pip install -r requirements.txt
start-hub.bat
```

`start-hub.bat` menjalankan `backend/main.py` (port 8081) dan `redirect.py` (port 8082). Di homelab keduanya autostart lewat Windows Scheduled Task `AelfLab_Hub` dan `AelfLab_Redirect`.

Dokumentasi API otomatis tersedia di `/docs`.

### Konfigurasi

Nilai dibaca dari environment variable, dan kalau kosong dari `$HERMES_HOME/.env`. Lihat `.env.example`:

| Variable | Fungsi kalau kosong |
|---|---|
| `HERMES_HOME` | default `D:/homelab/hermes` |
| `DEEPSEEK_API_KEY` | kartu saldo tampil `—` |
| `TELEGRAM_BOT_TOKEN` | notifikasi cron dilewati |
| `TELEGRAM_CHAT_ID` | notifikasi cron dilewati |
| `FINANCE_DB` | default `<hub>/data/finance.db` |

Tidak ada autentikasi di level aplikasi — akses eksternal diamankan **Cloudflare Access** di depan Cloudflare Tunnel. Jangan ekspos port 8081 langsung ke internet.

---

## Struktur

```
backend/
  main.py         monitoring, cron manager, subdomain routing
  finance.py      /api/finance/*
  pdf/main.py     /api/pdf/*
  clean_db.py     maintenance: gabung akun duplikat + rekalkulasi saldo
  *.ps1           script pengambilan metrik GPU & network
index.html        dashboard
finance.html      finance tracker
pdf.html          PDF editor
redirect.py       301 aelflab.com -> hub.aelflab.com (port 8082)
data/             runtime — upload, output, signature, DB, history (gitignored)
```

### Maintenance

```bat
python backend\clean_db.py
```

Menggabungkan akun duplikat (referensi transaksi diarahkan ulang lebih dulu supaya tidak ada transaksi orphan), membuang transaksi bernilai 0, lalu merekalkulasi saldo dari transaksi. Backup dibuat otomatis sebelum ada perubahan.

---

## Catatan & keterbatasan

- **Windows-only.** Seluruh monitoring bergantung pada `powershell.exe`. Tidak ada containerisasi karena hal ini; deployment memakai Scheduled Task.
- **Recurring belum berjalan sendiri.** Jatuh tempo sudah dihitung dan bisa dieksekusi lewat `POST /api/finance/recurring/run-due`, tapi masih perlu dipicu — dari UI, atau dijadwalkan sebagai cron job Hermes. Belum ada scheduler internal.
- **Tipe `invest` tidak mengubah saldo akun**, sementara `saving` menambah saldo. Aturan ini dipertahankan agar konsisten dengan data historis; mengubahnya butuh migrasi data yang disengaja.
- History hanya tercatat saat `/api/status` diakses, jadi grafik berlubang kalau dashboard lama tidak dibuka.
