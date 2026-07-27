#!/usr/bin/env python3
"""Bersihkan database finance: gabung akun duplikat & rekalkulasi saldo.

Jalankan dari root hub:  python backend/clean_db.py

Path database mengikuti finance.py (HUB_DIR/data/finance.db), bukan absolute
path, supaya script ini tetap benar di mesin mana pun. Bisa dioverride lewat
env FINANCE_DB.

Sebuah backup dibuat otomatis sebelum ada perubahan.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FINANCE_DB", HUB_DIR / "data" / "finance.db"))


def main() -> int:
    if not DB_PATH.exists():
        print(f"❌ Database tidak ditemukan: {DB_PATH}")
        print("   Set env FINANCE_DB kalau lokasinya berbeda.")
        return 1

    backup = DB_PATH.with_name(f"{DB_PATH.stem}.backup-{datetime.now():%Y%m%d_%H%M%S}.db")
    shutil.copy2(DB_PATH, backup)
    print(f"🗄  Backup: {backup.name}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    print(f"\n=== SEBELUM ({DB_PATH}) ===")
    print("Akun:")
    for a in conn.execute("SELECT * FROM accounts ORDER BY name").fetchall():
        print(f'  id={a["id"]} {a["name"]}: Rp{a["balance"]:,.0f}')
    print(f'\nTransaksi: {conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}')

    # ── 1. Gabungkan akun duplikat ──
    # Simpan id terkecil dan arahkan semua referensi ke sana lebih dulu, supaya
    # tidak ada transaksi yang kehilangan akunnya.
    kept = {r["name"]: r["min_id"]
            for r in conn.execute("SELECT name, MIN(id) AS min_id FROM accounts GROUP BY name")}

    merged = 0
    for name, keep_id in kept.items():
        dupes = conn.execute("SELECT id FROM accounts WHERE name=? AND id!=?", (name, keep_id)).fetchall()
        for d in dupes:
            old_id = d["id"]
            conn.execute("UPDATE transactions SET account_id=? WHERE account_id=?", (keep_id, old_id))
            conn.execute("UPDATE transactions SET account_to_id=? WHERE account_to_id=?", (keep_id, old_id))
            conn.execute("UPDATE investments SET account_id=? WHERE account_id=?", (keep_id, old_id))
            conn.execute("UPDATE installments SET account_id=? WHERE account_id=?", (keep_id, old_id))
            conn.execute("UPDATE recurring SET account_id=? WHERE account_id=?", (keep_id, old_id))
            conn.execute("DELETE FROM accounts WHERE id=?", (old_id,))
            merged += 1
    print(f"\nAkun duplikat digabung: {merged}")

    # ── 2. Buang transaksi kosong (sebelum rekalkulasi saldo) ──
    conn.execute("DELETE FROM transactions WHERE amount = 0 OR amount IS NULL")
    dropped = conn.execute("SELECT changes()").fetchone()[0]
    if dropped:
        print(f"Transaksi 0/null dihapus: {dropped}")

    # ── 3. Rekalkulasi saldo dari transaksi yang tersisa ──
    conn.execute("""
        UPDATE accounts SET balance = (
            SELECT COALESCE(SUM(
                CASE
                    WHEN t.type IN ('income', 'saving') THEN t.amount
                    WHEN t.type = 'transfer' AND t.account_to_id = accounts.id THEN t.amount
                    WHEN t.type = 'transfer' AND t.account_id = accounts.id THEN -t.amount
                    WHEN t.type = 'expense' THEN -t.amount
                    ELSE 0
                END
            ), 0)
            FROM transactions t
            WHERE t.account_id = accounts.id OR t.account_to_id = accounts.id
        )
    """)
    conn.commit()

    print("\n=== SESUDAH ===")
    print("Akun:")
    for a in conn.execute("SELECT * FROM accounts ORDER BY name").fetchall():
        print(f'  {a["name"]}: Rp{a["balance"]:,.0f} ({a["type"]})')
    print(f'Transaksi: {conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}')
    conn.close()

    print(f"\n✅ Database bersih. Kalau hasilnya tidak sesuai, pulihkan dari {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
