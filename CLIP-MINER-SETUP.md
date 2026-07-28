# Aktivasi Clip Miner

Checklist untuk agent. Kerjakan **satu langkah, laporkan hasil, tunggu konfirmasi**
sebelum lanjut. Jangan gabung beberapa langkah.

Aplikasinya **sudah ada** di GitHub: `titostream27/youtube-content-miner` (branch
`main`, 114 file, sudah ada Dockerfile + compose). **Jangan dibuat dari nol.**

Referensi lengkap: `docs/DEPLOYMENT.md` di repo tersebut.

---

## Ringkasan

| Item | Nilai |
|---|---|
| Port | **8083** (jangan 3000 — dipakai Open WebUI) |
| Path | `D:\homelab\hermes-workspace\content-miner` |
| Hostname | `miner.aelflab.com` |
| Database | SQLite di volume Docker, bukan di image |
| Auth | Cloudflare Access (bukan Basic Auth) |

Urutan sengaja begini: hub dulu karena paling aman, DNS terakhir karena aplikasi
punya endpoint yang menyimpan API key.

---

## Langkah 1 — Restart Hub

Tidak bergantung pada apa pun. Bisa dikerjakan sekarang.

```powershell
Restart-ScheduledTask -TaskName "AelfLab_Hub"
```

Verifikasi:

```powershell
curl.exe -s http://127.0.0.1:8081/api/status | Select-String '"miner"'
```

**Diharapkan:** `"miner":"Offline"`

`Offline` di sini **benar** — container Clip Miner memang belum ada. Yang penting
field `miner` muncul dan `/api/status` tetap 200. Kalau `/api/status` gagal total,
berhenti dan laporkan.

Cek juga kartu "Clip Miner" muncul di https://hub.aelflab.com.

---

## Langkah 2 — Clone repo

```powershell
git clone https://github.com/titostream27/youtube-content-miner.git D:\homelab\hermes-workspace\content-miner
cd D:\homelab\hermes-workspace\content-miner
Copy-Item .env.example .env
```

Verifikasi:

```powershell
Test-Path Dockerfile, docker-compose.yml, package.json
```

**Diharapkan:** `True` tiga kali.

Kalau ada yang `False`, branch-nya salah — pastikan `main`.

`.env` boleh dibiarkan kosong dulu. Aplikasi jalan penuh tanpa API key apa pun
(katalog demo + heuristic engine). Isi API key nanti di langkah 6.

---

## Langkah 3 — Build & jalankan container

```powershell
cd D:\homelab\hermes-workspace\content-miner
docker compose up -d --build
```

**Butuh 5–10 menit.** `better-sqlite3` dikompilasi dari sumber dan Next.js
di-build. Image hasilnya ~900 MB. Ini normal, jangan dibatalkan.

Verifikasi:

```powershell
docker compose ps
curl.exe -s http://127.0.0.1:8083/api/health
```

**Diharapkan:** container `running`, dan JSON berisi `"status":"ok"` +
`"database":"connected"`.

Kalau build gagal, ambil 30 baris terakhir log dan laporkan — jangan coba
perbaiki sendiri:

```powershell
docker compose logs --tail=30 app
```

---

## Langkah 4 — Isi data awal

```powershell
docker compose exec app npm run db:seed
```

**Diharapkan (tanpa YOUTUBE_API_KEY):**

```
episodes discovered : 12
episodes analysed   : 8
clips in library    : 7
```

Ini data demo sintetis — bukan podcast sungguhan. Wajar pada tahap ini.

Verifikasi hub sudah membaca:

```powershell
curl.exe -s http://127.0.0.1:8081/api/status | Select-String '"miner"'
```

**Diharapkan:** `"miner":"7 clips (demo)"`

Akhiran `(demo)` artinya `YOUTUBE_API_KEY` belum diisi. Itu penanda penting:
tanpa key, pipeline menyajikan katalog sintetis alih-alih gagal — mudah
disalahartikan sebagai hasil nyata.

---

## Langkah 5 — DNS + Cloudflare Access

**Kerjakan paling akhir.** Sebelum hostname aktif, pastikan policy Access sudah
ada. Aplikasi ini punya endpoint tulis:

| Endpoint | Kalau terbuka tanpa auth |
|---|---|
| `PUT /api/settings/transcript` | Menulis API key vendor |
| `POST /api/runs` | Menghabiskan kredit AI + kuota YouTube |

### 5a. Route DNS

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel route dns <tunnel-id> miner.aelflab.com
```

### 5b. Ingress rule

Tambahkan ke `C:\Users\Home\.cloudflared\config.yml`:

```yaml
  - hostname: miner.aelflab.com
    service: http://127.0.0.1:8083
```

Lalu salin ke config service dan restart cloudflared — pola yang sama seperti
perubahan tunnel lainnya di host ini.

### 5c. Konfirmasi policy Access

Cek policy Access untuk `miner.aelflab.com` **secara spesifik**. Jangan asumsikan
tercakup policy wildcard.

`AGENTS.md` mencatat bahwa `finance.aelflab.com` dan `pdf.aelflab.com` pun belum
terkonfirmasi tercakup. Kalau policy belum bisa dipastikan, aktifkan lapisan
sementara di `.env`:

```
APP_BASIC_AUTH_USER=operator
APP_BASIC_AUTH_PASSWORD=<string acak panjang>
```

lalu `docker compose up -d`. Ini **bukan** pengganti Access — hanya jaring supaya
endpoint penulis API key tidak terbuka. Matikan setelah Access terkonfirmasi.

Verifikasi: buka https://miner.aelflab.com — harus kena challenge Access dulu,
bukan langsung masuk dashboard.

---

## Langkah 6 — Uji jalur transcript (menentukan biaya)

Ini menentukan apakah perlu bayar vendor transcript atau tidak.

```powershell
docker compose exec app npx tsx scripts/diagnose-transcript.ts <videoId>
```

Pakai **episode podcast asli 1–3 jam**, bukan klip pendek. Truncation dan
penanganan job async hanya muncul di video panjang.

**Kalau `ytdlp` berhasil** — selesai, tidak perlu bayar apa pun. Set di `.env`:

```
TRANSCRIPT_PROVIDERS=ytdlp,captions
```

Homelab ini pakai IP residensial. Pemblokiran YouTube yang terukur bersifat
khusus IP datacenter, jadi peluang berhasil besar.

**Kalau semua provider melaporkan blocked** — laporkan output persisnya. Opsinya
residential proxy (`YTDLP_PROXY`) atau vendor berbayar yang dipilih dari UI
(AI Agents → Transcript vendor). Jangan pilih sendiri, tanya user dulu.

---

## Langkah 7 — Opsional: API key & jadwal

### API key

Isi di `.env` lalu `docker compose up -d`:

- `YOUTUBE_API_KEY` — discovery podcast sungguhan (akhiran `(demo)` hilang)
- Satu key AI provider apa pun — scoring naik dari heuristic ke LLM

Ollama lokal juga didukung: `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`

### Scheduled task

Pakai CLI, **bukan** HTTP — route punya batas 300 detik.

```powershell
$dir = "D:\homelab\hermes-workspace\content-miner"
schtasks /create /tn "AelfLab_Miner_Backup" /tr "cmd /c cd /d $dir && docker compose exec -T app scripts/backup-db.sh /data/backups" /sc daily /st 03:30 /f
```

Backup dulu sebelum discovery terjadwal. Tabel `clip_feedback` tidak bisa
dibuat ulang.

---

## Kalau perlu rollback

```powershell
cd D:\homelab\hermes-workspace\content-miner
docker compose down
```

Hub tetap jalan, monitoring kembali `Offline`. Data tetap di volume
`content-miner-data` — `docker compose down` tidak menghapusnya.

---

## Yang jangan dilakukan

- Jangan bikin aplikasi Clip Miner dari nol — sudah ada di GitHub
- Jangan pakai port 3000 — Open WebUI
- Jangan mount Clip Miner ke dalam proses FastAPI Hub — aplikasi Next.js
  terpisah dengan database sendiri, bukan router Python
- Jangan ekspos port 8083 langsung ke internet
- Jangan buka `miner.aelflab.com` sebelum policy Access dikonfirmasi
- Jangan tampilkan isi API key di output
