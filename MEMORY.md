Cron jobs: Daily Homelab Health Check (0 9 * * *, ac97810aa3b1), Homelab Alerts (0 * * * *, d00464f3c4f9).
§
Finance tracker: catat transaksi via curl ke localhost:8081/api/finance/transactions. Pola: "kopi 12rb"=expense Minuman, "gaji 5jt"=income Gaji, "nabung 300rb"=saving Tabungan, "transfer 500rb BCA ke Jenius"=transfer. Cek saldo: curl localhost:8081/api/finance/summary. Portfolio: curl localhost:8081/api/finance/portfolio. Kategori: Makanan, Minuman, Transport, Belanja, Hiburan, Kesehatan, Tagihan, Kos/Sewa, Gaji, Bonus, Tabungan, Investasi. Akun: Tunai, BCA, Jenius, GoPay.
§
Finance tracker backend: hub.aelflab.com/api/finance. Transaksi via curl. Ada dashboard di hub.aelflab.com/finance. Fitur: recurring, cicilan, budgeting, investasi, transfer, export Excel.
§
Finance tracker aktif: catat transaksi via chat natural (e.g. "kopi 12rb", "gaji 5jt"). Akun: BCA, Jenius, GoPay, Tunai, Superbank. Gaji tgl 25 + sewa 2.5jt + nafkah istri 3jt juga tgl 25. Dashboard finance di finance.aelflab.com.
§
Ada startup notifier via Windows Task Scheduler (Hermes_StartupNotif) — kirim notif Telegram "🟢 PC Nyala!" 30 detik setelah boot. Script di D:\homelab\hermes\scripts\startup-notif.bat. Token Telegram dari .env.
§
Finance tracker built: backend (FastAPI+SQLite) + frontend (hub.aelflab.com/finance) + Telegram chat integration. API di localhost:8081/api/finance. Export Excel di /api/finance/export. Auto-parse transaksi dari chat natural: "kopi 12rb", "gaji 5jt", "transfer 200rb BCA ke Superbank". Kategori: Makanan, Minuman, Transport, Belanja, Hiburan, Kesehatan, Tagihan, Kos/Sewa, Gaji, Bonus, Tabungan, Investasi, Nafkah. Akun: Tunai, BCA, Jenius, GoPay, Superbank. Subdomain finance.aelflab.com → 8081 (serve finance.html by host header).
§
Finance Tracker: backend di hub/backend/finance.py, frontend di hub/finance.html, DB di hub/data/finance.db. API prefix /api/finance. Akses via hub.aelflab.com/finance atau finance.aelflab.com. Subdomain finance via Cloudflare tunnel config + host-based routing di main.py.
§
Finance tracker preferences: format transaksi sangat ringkas — "✅ Tercatat: Rp{amount} — {category}" langsung tanpa basa-basi. Untuk recurring: Gaji tgl 25 Rp12.119.213 (income), Sewa kontrakan tgl 25 Rp2.500.000 (expense), Nafkah Istri tgl 25 Rp3.000.000 (expense). Akun: BCA, Jenius, GoPay, Tunai, Superbank. Kategori kustom: Nafkah.
§
Finance tracker: database di D:\homelab\hermes-workspace\hub\data\finance.db. API di port 8081/api/finance/. Frontend di hub.aelflab.com/finance dan finance.aelflab.com. Akun: BCA, Superbank, Tunai, Jenius, GoPay. Recurring: Gaji (tgl 25, Rp12.119.213), Sewa Kontrakan (tgl 25, Rp2.500.000), Nafkah Istri (tgl 25, Rp3.000.000). Startup notif via Scheduled Task Hermes_StartupNotif.
§
Finance tracker: backend di D:\homelab\hermes-workspace\hub\backend\finance.py, API di /api/finance/*, frontend di /finance. Database SQLite di hub/data/finance.db. Jadwal recurring: Gaji+sewa+nafkah tgl 25. Akun: BCA, Tunai, Jenius, GoPay, Superbank.
