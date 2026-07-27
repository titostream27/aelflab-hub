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
- Redirect aelflab.com ke hub.aelflab.com berjalan pada port 8082.
- Autostart Hub dan Redirect menggunakan Windows Scheduled Tasks AelfLab_Hub dan AelfLab_Redirect.
- Cloudflare Tunnel aelflab: ai.aelflab.com ke port 3000, hub.aelflab.com ke port 8081, dan aelflab.com ke port 8082.
- Cloudflare Access aktif.
- Konfigurasi Cloudflare user: C:\Users\Home\.cloudflared\config.yml.
- Konfigurasi service: C:\Windows\System32\config\systemprofile\.cloudflared\config.yml.
- Setelah mengubah konfigurasi user, salin ke konfigurasi service lalu restart service cloudflared.
- Tambahkan DNS tunnel dengan: "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel route dns <tunnel-id> <hostname>.
- Jika subprocess berhasil di terminal tetapi gagal dari FastAPI, periksa perbedaan PATH dan virtual environment.
- Gunakan absolute path executable atau Python venv; jangan mengandalkan bare "python".
- Gunakan timeout minimal 120 detik untuk operasi berbasis LLM.