# Konteks AelfLab Homelab

- Sistem operasi host: Windows 11.
- Root proyek: D:\homelab.
- Hermes home: D:\homelab\hermes.
- Workspace Hermes: D:\homelab\hermes-workspace.
- Hermes Agent: versi 0.19.0.
- Model utama: DeepSeek V4 Flash melalui DeepSeek API.
- Kandidat model lokal/fallback: qwen3.5-hermes:9b melalui Ollama.
- Endpoint Ollama: http://localhost:11434/v1.
- Ollama yang terakhir diamati: versi 0.32.4.
- Hardware: Intel i5-13400F, RAM 32 GB, RX 6700 XT 12 GB.
- qwen3.5-hermes:9b menggunakan context 65536 dan dapat berjalan 100% GPU.
- Telegram gateway menggunakan allowlist.
- Gateway dijalankan otomatis melalui Scheduled Task bernama Hermes_Gateway.
- Open WebUI dan Cloudflare Tunnel sudah ada. Jangan mengubahnya tanpa permintaan eksplisit.
- DeepSeek menggunakan inferensi cloud; Hermes, gateway, dan tool berjalan pada homelab.
- Jangan pernah menampilkan API key, token Telegram, isi .env, atau kredensial.
- Konfigurasi Hub dibaca dari environment variable, fallback ke $HERMES_HOME\.env: DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HERMES_HOME, FINANCE_DB. Template ada di .env.example. Jangan hardcode nilai apa pun dari daftar ini ke dalam source.
- Verifikasi status service menggunakan perintah read-only sebelum melaporkannya.
- Simpan file kerja agent secara default di D:\homelab\hermes-workspace.

## Source of Truth

- Sistem operasi yang telah diverifikasi langsung melalui PowerShell adalah Windows 11.
- Jika metadata runtime menyebut Windows 10, perlakukan sebagai hasil deteksi kompatibilitas dan bukan sumber utama versi Windows.
- Jika terdapat konflik fakta, laporkan konfliknya dan prioritaskan hasil pemeriksaan langsung terbaru.
## Operasional AelfLab

- Saat membantu konfigurasi homelab, lakukan satu langkah aman per giliran dan tunggu hasil pengguna sebelum melanjutkan.
- AelfLab Hub tersedia di https://hub.aelflab.com.
- Backend FastAPI: D:\homelab\hermes-workspace\hub\backend\main.py pada port 8081.
- Satu proses FastAPI melayani tiga aplikasi sekaligus, dibedakan dari header Host: hub (monitoring), finance.aelflab.com (finance tracker), pdf.aelflab.com (PDF editor). Path /finance dan /pdf tersedia sebagai alternatif.
- Redirect aelflab.com ke hub.aelflab.com berjalan pada port 8082 melalui redirect.py.
- Autostart Hub dan Redirect menggunakan Windows Scheduled Tasks AelfLab_Hub dan AelfLab_Redirect.
- Hub tidak dikontainerisasi. Seluruh monitoring memanggil powershell.exe sehingga hanya bisa berjalan native di Windows.
- Dependensi backend dipasang dari requirements.txt.
- Cloudflare Tunnel aelflab: ai.aelflab.com ke port 3000, hub.aelflab.com ke port 8081, dan aelflab.com ke port 8082.
- Cloudflare Access aktif.
- Belum terverifikasi: hostname finance.aelflab.com dan pdf.aelflab.com dipakai oleh aplikasi tetapi tidak tercatat dalam daftar route tunnel maupun policy Access di atas. Periksa "cloudflared tunnel route dns" dan policy Access untuk kedua hostname sebelum menganggapnya terlindungi.
- Tidak ada autentikasi di level aplikasi. Seluruh /api/* mengandalkan Cloudflare Access. Jangan ekspos port 8081 langsung ke internet.
- Konfigurasi Cloudflare user: C:\Users\Home\.cloudflared\config.yml.
- Konfigurasi service: C:\Windows\System32\config\systemprofile\.cloudflared\config.yml.
- Setelah mengubah konfigurasi user, salin ke konfigurasi service lalu restart service cloudflared.
- Tambahkan DNS tunnel dengan: "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel route dns <tunnel-id> <hostname>.
- Jika subprocess berhasil di terminal tetapi gagal dari FastAPI, periksa perbedaan PATH dan virtual environment.
- Gunakan absolute path executable atau Python venv; jangan mengandalkan bare "python".
- Gunakan timeout minimal 120 detik untuk operasi berbasis LLM.


## Podcast Clip Miner

- Langkah aktivasi lengkap ada di CLIP-MINER-SETUP.md pada repo ini. Ikuti berurutan, satu langkah per giliran.
- Repo terpisah: titostream27/youtube-content-miner. Bukan bagian dari repo Hub.
- Aplikasinya sudah lengkap di branch main, termasuk Dockerfile dan docker-compose. Jangan membuat ulang dari nol.
- Fungsi: menambang momen terbaik dari podcast YouTube untuk dijadikan konten short-form.
- Berjalan sebagai container Docker pada port 8083, bukan native seperti Hub.
- Port 8083 dipilih mengikuti konvensi lokal: 8081 Hub, 8082 redirect. Port 3000 tidak boleh dipakai karena sudah milik Open WebUI.
- Tidak di-mount sebagai router di dalam proses FastAPI Hub. Aplikasinya Next.js dengan database SQLite sendiri, sehingga pola finance dan pdf tidak berlaku.
- Hub berperan sebagai launcher: satu kartu di appGrid menuju https://miner.aelflab.com, dan satu baris monitoring yang membaca GET http://127.0.0.1:8083/api/health.
- Path /miner pada Hub mengembalikan redirect 307 ke subdomain, bukan FileResponse. Hub tidak menjadi reverse proxy.
- Alamat service dapat dioverride dengan environment variable MINER_URL.
- Probe health tidak boleh melempar exception. Jika container mati, monitoring menampilkan "Offline" dan endpoint /api/status tetap berhasil.
- Status yang mengandung "(demo)" berarti YOUTUBE_API_KEY belum diisi dan pipeline sedang menyajikan katalog sintetis, bukan podcast sungguhan.
- Database berada pada volume Docker, bukan pada layer image. Tabel clip_feedback tidak dapat dibuat ulang dan wajib masuk rencana backup.
- Discovery terjadwal menggunakan CLI di dalam container melalui Windows Scheduled Task, mengikuti pola AelfLab_Hub dan AelfLab_Redirect. Jangan memakai HTTP untuk pekerjaan terjadwal karena route memiliki batas 300 detik.
- Uji jalur transcript gratis lebih dulu sebelum menyarankan vendor berbayar. Homelab memakai IP residensial, sedangkan pemblokiran YouTube yang terukur bersifat khusus IP datacenter.

### Belum terverifikasi untuk Clip Miner

- Route tunnel miner.aelflab.com ke port 8083 belum dibuat. Tambahkan dengan "cloudflared tunnel route dns <tunnel-id> miner.aelflab.com", lalu salin konfigurasi user ke konfigurasi service dan restart cloudflared.
- Policy Cloudflare Access untuk miner.aelflab.com belum dikonfirmasi. Ini lebih penting daripada pada finance dan pdf: Clip Miner memiliki endpoint tulis PUT /api/settings/transcript yang menyimpan API key vendor, dan POST /api/runs yang menghabiskan kredit AI serta kuota YouTube. Verifikasi policy sebelum hostname diekspos.
- Selama policy Access belum dikonfirmasi, aktifkan HTTP Basic auth bawaan aplikasi sebagai lapisan sementara dengan APP_BASIC_AUTH_USER dan APP_BASIC_AUTH_PASSWORD. Nonaktif secara default dan bukan pengganti Cloudflare Access.
