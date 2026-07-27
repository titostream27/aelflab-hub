"""Bersihkan database finance: hapus duplikat akun & transaksi orphan."""
import sqlite3

DB = 'D:/homelab/hermes-workspace/hub/data/finance.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=== SEBELUM ===")
print("Akun:")
for a in conn.execute('SELECT * FROM accounts ORDER BY name').fetchall():
    print(f'  id={a["id"]} {a["name"]}: Rp{a["balance"]:,.0f}')

print(f'\nTransaksi: {conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}')

# ── 1. Hapus duplikat akun ──
# Strategi: untuk setiap nama, keep id terkecil (karena history transaksi)
kept = {}  # name -> id to keep
for row in conn.execute('SELECT name, MIN(id) as min_id FROM accounts GROUP BY name').fetchall():
    kept[row['name']] = row['min_id']

deleted_count = 0
for name, keep_id in kept.items():
    dupes = conn.execute('SELECT id FROM accounts WHERE name=? AND id!=?', (name, keep_id)).fetchall()
    for d in dupes:
        old_id = d['id']
        # Update transaksi yang refer ke akun duplikat
        conn.execute('UPDATE transactions SET account_id=? WHERE account_id=?', (keep_id, old_id))
        conn.execute('UPDATE transactions SET account_to_id=? WHERE account_to_id=?', (keep_id, old_id))
        conn.execute('UPDATE investments SET account_id=? WHERE account_id=?', (keep_id, old_id))
        conn.execute('UPDATE installments SET account_id=? WHERE account_id=?', (keep_id, old_id))
        conn.execute('UPDATE recurring SET account_id=? WHERE account_id=?', (keep_id, old_id))
        conn.execute('DELETE FROM accounts WHERE id=?', (old_id,))
        deleted_count += 1

print(f'\nDuplikat dihapus: {deleted_count}')

# ── 2. Rekalkulasi balance ──
conn.execute('''
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
''')
conn.commit()

# ── 3. Hapus transaksi dengan amount 0 (kalau ada) ──
conn.execute("DELETE FROM transactions WHERE amount = 0 OR amount IS NULL")
deleted_tx = conn.execute("SELECT changes()").fetchone()[0]
if deleted_tx:
    print(f'Transaksi 0/null dihapus: {deleted_tx}')

conn.commit()

print("\n=== SESUDAH ===")
print("Akun:")
for a in conn.execute('SELECT * FROM accounts ORDER BY name').fetchall():
    print(f'  {a["name"]}: Rp{a["balance"]:,.0f} ({a["type"]})')
print(f'Transaksi: {conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}')

conn.close()
print("\n✅ Database bersih!")
