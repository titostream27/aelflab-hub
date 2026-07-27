import sqlite3
conn = sqlite3.connect('D:/homelab/hermes-workspace/hub/data/finance.db')
conn.row_factory = sqlite3.Row

# Cari duplikat
dupes = conn.execute('SELECT name, COUNT(*) as cnt, MAX(id) as keep_id FROM accounts GROUP BY name HAVING cnt > 1').fetchall()
print(f'Duplikat ditemukan: {len(dupes)}')
for d in dupes:
    # Hapus semua kecuali id tertinggi
    conn.execute('DELETE FROM accounts WHERE name=? AND id!=?', (d['name'], d['keep_id']))
    print(f'  {d["name"]}: keep id={d["keep_id"]}, hapus lainnya')

conn.commit()

# Verifikasi
for a in conn.execute('SELECT * FROM accounts ORDER BY name').fetchall():
    print(f'  {a["name"]} (id={a["id"]}): Rp{a["balance"]:,.0f}')

# Update balance dari transaksi
conn.execute('''
    UPDATE accounts SET balance = (
        SELECT COALESCE(SUM(CASE WHEN t.type IN ('income','saving') THEN t.amount ELSE 0 END),0)
        - COALESCE(SUM(CASE WHEN t.type='expense' THEN t.amount ELSE 0 END),0)
        + COALESCE(SUM(CASE WHEN t.type='transfer' AND t.account_to_id=accounts.id THEN t.amount ELSE 0 END),0)
        - COALESCE(SUM(CASE WHEN t.type='transfer' AND t.account_id=accounts.id THEN t.amount ELSE 0 END),0)
        FROM transactions t WHERE t.account_id=accounts.id OR t.account_to_id=accounts.id
    )
''')
conn.commit()
print('\nSaldo setelah update:')
for a in conn.execute('SELECT * FROM accounts ORDER BY name').fetchall():
    print(f'  {a["name"]}: Rp{a["balance"]:,.0f}')

conn.close()
