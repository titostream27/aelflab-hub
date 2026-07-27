"""
AelfLab Finance — Backend API
Database + endpoints untuk pencatatan keuangan pribadi
"""
import os, json, sqlite3, subprocess
from pathlib import Path
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

HUB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = HUB_DIR / "data" / "finance.db"

router = APIRouter(prefix="/api/finance", tags=["finance"])


# ── Database ──────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL DEFAULT 'cash',
            balance REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            icon TEXT DEFAULT '📦',
            type TEXT NOT NULL DEFAULT 'expense'
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT (date('now','localtime')),
            time TEXT DEFAULT (time('now','localtime')),
            type TEXT NOT NULL CHECK(type IN ('income','expense','transfer','invest','saving')),
            amount REAL NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            account_id INTEGER REFERENCES accounts(id),
            account_to_id INTEGER REFERENCES accounts(id),
            note TEXT,
            merchant TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER REFERENCES categories(id),
            month TEXT NOT NULL,
            amount REAL NOT NULL,
            spent REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'expense',
            amount REAL NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            account_id INTEGER REFERENCES accounts(id),
            frequency TEXT NOT NULL DEFAULT 'monthly',
            day INTEGER NOT NULL DEFAULT 1,
            next_date TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS installments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            total_amount REAL NOT NULL,
            total_installments INTEGER NOT NULL,
            paid_installments INTEGER DEFAULT 0,
            monthly_amount REAL NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            account_id INTEGER REFERENCES accounts(id),
            start_date TEXT NOT NULL,
            end_date TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('crypto','gold','stock','mutual_fund','forex','deposit','other')),
            amount REAL NOT NULL,
            quantity REAL,
            buy_price REAL,
            current_price REAL,
            currency TEXT DEFAULT 'IDR',
            account_id INTEGER REFERENCES accounts(id),
            maturity_date TEXT,
            return_rate REAL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()

    # Seed default categories
    cats = [
        ('Makanan', '🍜', 'expense'), ('Minuman', '☕', 'expense'),
        ('Transport', '🚗', 'expense'), ('Belanja', '🛒', 'expense'),
        ('Hiburan', '🎮', 'expense'), ('Kesehatan', '💊', 'expense'),
        ('Tagihan', '📋', 'expense'), ('Kos/Sewa', '🏠', 'expense'),
        ('Gaji', '💰', 'income'), ('Bonus', '🎁', 'income'),
        ('Tabungan', '🏦', 'saving'), ('Investasi', '📈', 'invest'),
    ]
    for name, icon, typ in cats:
        conn.execute("INSERT OR IGNORE INTO categories(name, icon, type) VALUES (?,?,?)", (name, icon, typ))

    # Seed default accounts
    for acct in [('Tunai', 'cash'), ('BCA', 'bank'), ('Jenius', 'bank'), ('GoPay', 'ewallet')]:
        conn.execute("INSERT OR IGNORE INTO accounts(name, type) VALUES (?,?)", acct)

    conn.commit()
    conn.close()

init_db()


# ── Models ────────────────────────────────────────

class TransactionIn(BaseModel):
    type: str  # income/expense/transfer/invest/saving
    amount: float
    category: Optional[str] = None
    account: Optional[str] = None
    account_to: Optional[str] = None
    note: Optional[str] = None
    merchant: Optional[str] = None
    date: Optional[str] = None

class BudgetIn(BaseModel):
    category: str
    month: str  # YYYY-MM
    amount: float

class RecurringIn(BaseModel):
    name: str
    type: str = 'expense'
    amount: float
    category: Optional[str] = None
    account: Optional[str] = None
    frequency: str = 'monthly'
    day: int = 1

class InstallmentIn(BaseModel):
    name: str
    total_amount: float
    total_installments: int
    monthly_amount: float
    category: Optional[str] = None
    account: Optional[str] = None
    start_date: Optional[str] = None

class InvestmentIn(BaseModel):
    name: str
    type: str
    amount: float
    quantity: Optional[float] = None
    buy_price: Optional[float] = None
    account: Optional[str] = None
    maturity_date: Optional[str] = None
    return_rate: Optional[float] = None
    note: Optional[str] = None


# ── Helpers ───────────────────────────────────────

def get_or_create(conn, table, name_field, name, extra=None):
    row = conn.execute(f"SELECT id FROM {table} WHERE {name_field}=?", (name,)).fetchone()
    if row:
        return row['id']
    if extra:
        conn.execute(f"INSERT INTO {table}({name_field}, {extra[0]}) VALUES (?,?)", (name, extra[1]))
    else:
        conn.execute(f"INSERT INTO {table}({name_field}) VALUES (?)", (name,))
    conn.commit()
    return conn.execute(f"SELECT id FROM {table} WHERE {name_field}=?", (name,)).fetchone()['id']

def fetch_crypto_price(coin_id: str = "bitcoin") -> Optional[float]:
    """Get current BTC/ETH price in IDR from CoinGecko."""
    try:
        r = subprocess.run(
            ["curl", "-sk", f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=idr"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        return data.get(coin_id, {}).get("idr")
    except: return None

def fetch_gold_price() -> Optional[float]:
    """Get current gold price per gram in IDR (Antam via Pegadaian API)."""
    try:
        r = subprocess.run(
            ["curl", "-sk", "https://harga-emas.org/"],
            capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.splitlines():
            if "1 gram" in line and "Rp" in line:
                import re
                m = re.search(r'Rp[.\s]*([\d,.]+)', line)
                if m: return float(m.group(1).replace('.','').replace(',',''))
    except: return None


# ── Endpoints ─────────────────────────────────────

@router.get("/init")
def api_init():
    """Re-seed database (safe to call anytime)."""
    init_db()
    return {"status": "ok"}

@router.get("/categories")
def list_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
    conn.close()
    return {"categories": [dict(r) for r in rows]}

@router.get("/accounts")
def list_accounts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    conn.close()
    return {"accounts": [dict(r) for r in rows]}

@router.post("/accounts")
def add_account(name: str = "", type: str = "cash"):
    conn = get_db()
    try:
        conn.execute("INSERT INTO accounts(name, type) VALUES (?,?)", (name, type))
        conn.commit()
        conn.close()
        return {"status": "ok", "account": {"name": name, "type": type, "balance": 0}}
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

@router.post("/transactions")
def add_transaction(t: TransactionIn):
    conn = get_db()
    cat_id = None
    if t.category:
        cat_id = get_or_create(conn, 'categories', 'name', t.category, ('type', t.type if t.type in ('income','expense') else 'expense'))
    acct_id = None
    if t.account:
        acct_id = get_or_create(conn, 'accounts', 'name', t.account)
    acct_to_id = None
    if t.account_to:
        acct_to_id = get_or_create(conn, 'accounts', 'name', t.account_to)

    tx_date = t.date or date.today().isoformat()
    conn.execute(
        "INSERT INTO transactions(date, type, amount, category_id, account_id, account_to_id, note, merchant) VALUES (?,?,?,?,?,?,?,?)",
        (tx_date, t.type, t.amount, cat_id, acct_id, acct_to_id, t.note, t.merchant)
    )
    tx_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Update account balance
    if acct_id and t.type in ('income', 'saving'):
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id=?", (t.amount, acct_id))
    elif acct_id and t.type in ('expense',):
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id=?", (t.amount, acct_id))
    elif acct_id and acct_to_id and t.type == 'transfer':
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id=?", (t.amount, acct_id))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id=?", (t.amount, acct_to_id))

    # Update budget spent
    if cat_id and t.type == 'expense':
        month = tx_date[:7]
        conn.execute("UPDATE budgets SET spent = spent + ? WHERE category_id=? AND month=?", (t.amount, cat_id, month))

    conn.commit()

    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    conn.close()
    return {"status": "ok", "transaction": dict(tx)}

@router.get("/transactions")
def list_transactions(limit: int = 20, offset: int = 0, month: Optional[str] = None):
    conn = get_db()
    sql = """
        SELECT t.*, c.name as cat_name, c.icon, a.name as acct_name, a2.name as acct_to_name
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        LEFT JOIN accounts a ON t.account_id = a.id
        LEFT JOIN accounts a2 ON t.account_to_id = a2.id
    """
    params = []
    if month:
        sql += " WHERE t.date LIKE ?"
        params.append(month + '%')
    sql += " ORDER BY t.date DESC, t.time DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM transactions" + (" WHERE date LIKE ?" if month else ""),
                         [month+'%'] if month else []).fetchone()[0]
    conn.close()
    return {"transactions": [dict(r) for r in rows], "total": total}

@router.get("/summary")
def monthly_summary(month: Optional[str] = None):
    """Ringkasan bulanan: pemasukan, pengeluaran, tabungan, sisa."""
    if not month:
        month = date.today().isoformat()[:7]

    conn = get_db()
    income = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date LIKE ?", (month+'%',)
    ).fetchone()[0]
    expense = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date LIKE ?", (month+'%',)
    ).fetchone()[0]
    saving = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='saving' AND date LIKE ?", (month+'%',)
    ).fetchone()[0]
    invest = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='invest' AND date LIKE ?", (month+'%',)
    ).fetchone()[0]

    # Spending by category
    cat_spending = conn.execute("""
        SELECT c.name, c.icon, SUM(t.amount) as total
        FROM transactions t JOIN categories c ON t.category_id = c.id
        WHERE t.type='expense' AND t.date LIKE ?
        GROUP BY c.id ORDER BY total DESC
    """, (month+'%',)).fetchall()

    # Budgets
    budgets = conn.execute("""
        SELECT b.*, c.name, c.icon FROM budgets b
        JOIN categories c ON b.category_id = c.id
        WHERE b.month=? ORDER BY c.name
    """, (month,)).fetchall()

    # Account balances
    accounts = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()

    # Active installments
    installments = conn.execute(
        "SELECT * FROM installments WHERE active=1 ORDER BY start_date"
    ).fetchall()

    conn.close()

    return {
        "month": month,
        "income": income,
        "expense": expense,
        "saving": saving,
        "invest": invest,
        "balance": income - expense,
        "cat_spending": [dict(r) for r in cat_spending],
        "budgets": [dict(r) for r in budgets],
        "accounts": [dict(r) for r in accounts],
        "installments": [dict(r) for r in installments],
    }

@router.post("/budgets")
def set_budget(b: BudgetIn):
    conn = get_db()
    cat_id = get_or_create(conn, 'categories', 'name', b.category)
    existing = conn.execute(
        "SELECT id, spent FROM budgets WHERE category_id=? AND month=?",
        (cat_id, b.month)
    ).fetchone()
    if existing:
        conn.execute("UPDATE budgets SET amount=? WHERE id=?", (b.amount, existing['id']))
    else:
        conn.execute(
            "INSERT INTO budgets(category_id, month, amount) VALUES (?,?,?)",
            (cat_id, b.month, b.amount)
        )
    conn.commit()
    conn.close()
    return {"status": "ok"}

@router.post("/recurring")
def add_recurring(r: RecurringIn):
    conn = get_db()
    cat_id = get_or_create(conn, 'categories', 'name', r.category) if r.category else None
    acct_id = get_or_create(conn, 'accounts', 'name', r.account) if r.account else None
    conn.execute(
        "INSERT INTO recurring(name, type, amount, category_id, account_id, frequency, day, next_date) VALUES (?,?,?,?,?,?,?,?)",
        (r.name, r.type, r.amount, cat_id, acct_id, r.frequency, r.day, None)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}

@router.post("/installments")
def add_installment(inst: InstallmentIn):
    conn = get_db()
    cat_id = get_or_create(conn, 'categories', 'name', inst.category) if inst.category else None
    acct_id = get_or_create(conn, 'accounts', 'name', inst.account) if inst.account else None
    start = inst.start_date or date.today().isoformat()
    conn.execute(
        "INSERT INTO installments(name, total_amount, total_installments, monthly_amount, category_id, account_id, start_date) VALUES (?,?,?,?,?,?,?)",
        (inst.name, inst.total_amount, inst.total_installments, inst.monthly_amount, cat_id, acct_id, start)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}

@router.get("/installments")
def list_installments():
    conn = get_db()
    rows = conn.execute("""
        SELECT i.*, c.name as cat_name, c.icon, a.name as acct_name
        FROM installments i
        LEFT JOIN categories c ON i.category_id = c.id
        LEFT JOIN accounts a ON i.account_id = a.id
        ORDER BY i.active DESC, i.start_date
    """).fetchall()
    conn.close()
    return {"installments": [dict(r) for r in rows]}

@router.post("/investments")
def add_investment(inv: InvestmentIn):
    conn = get_db()
    acct_id = get_or_create(conn, 'accounts', 'name', inv.account) if inv.account else None
    conn.execute(
        "INSERT INTO investments(name, type, amount, quantity, buy_price, account_id, maturity_date, return_rate, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (inv.name, inv.type, inv.amount, inv.quantity, inv.buy_price, acct_id, inv.maturity_date, inv.return_rate, inv.note)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}

@router.get("/investments")
def list_investments():
    conn = get_db()
    rows = conn.execute("""
        SELECT inv.*, a.name as acct_name
        FROM investments inv
        LEFT JOIN accounts a ON inv.account_id = a.id
        ORDER BY inv.created_at DESC
    """).fetchall()
    conn.close()

    # Auto-fetch current prices for crypto
    investments = [dict(r) for r in rows]
    for inv in investments:
        if inv['type'] == 'crypto' and inv['name'].lower() in ('bitcoin','btc'):
            price = fetch_crypto_price('bitcoin')
            if price: inv['current_price'] = price
        elif inv['type'] == 'crypto' and inv['name'].lower() in ('ethereum','eth'):
            price = fetch_crypto_price('ethereum')
            if price: inv['current_price'] = price
        elif inv['type'] == 'gold':
            price = fetch_gold_price()
            if price: inv['current_price'] = price

    return {"investments": investments}

@router.get("/portfolio")
def portfolio_summary():
    """Total portfolio value: crypto + gold + deposits + other investments."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM investments").fetchall()
    conn.close()

    total_cost = 0
    total_current = 0
    details = []
    for inv in rows:
        inv = dict(inv)
        cost = inv['amount']
        current = inv['amount']
        if inv['type'] == 'crypto' and inv['name'].lower() in ('bitcoin','btc'):
            price = fetch_crypto_price('bitcoin')
            if price and inv['quantity']:
                current = price * inv['quantity']
                inv['current_price'] = price
        elif inv['type'] == 'gold':
            price = fetch_gold_price()
            if price and inv['quantity']:
                current = price * inv['quantity']
                inv['current_price'] = price
        elif inv['type'] == 'deposit' and inv['maturity_date']:
            try:
                from datetime import datetime as dt
                start = dt.strptime(inv.get('created_at','')[:10], '%Y-%m-%d') if inv.get('created_at') else None
                if start and inv['return_rate']:
                    days = (dt.now() - start).days
                    interest = inv['amount'] * (inv['return_rate']/100) * days / 365
                    current = inv['amount'] + interest
            except: pass

        total_cost += cost
        total_current += current
        pnl = current - cost
        pnl_pct = (pnl / cost * 100) if cost else 0
        details.append({
            "name": inv['name'], "type": inv['type'],
            "cost": round(cost,2), "current": round(current,2),
            "pnl": round(pnl,2), "pnl_pct": round(pnl_pct,2)
        })

    return {
        "total_cost": round(total_cost,2),
        "total_current": round(total_current,2),
        "total_pnl": round(total_current - total_cost,2),
        "total_pnl_pct": round((total_current - total_cost) / total_cost * 100, 2) if total_cost else 0,
        "details": details
    }

from fastapi.responses import StreamingResponse
import io, openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

@router.get("/export")
def export_excel(month: Optional[str] = None):
    """Export transaksi ke file Excel (.xlsx)."""
    if not month:
        from datetime import date
        month = date.today().isoformat()[:7]

    conn = get_db()
    rows = conn.execute("""
        SELECT t.date, t.time, t.type, t.amount, c.name as cat, c.icon, a.name as acct, t.merchant, t.note
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        LEFT JOIN accounts a ON t.account_id = a.id
        WHERE t.date LIKE ?
        ORDER BY t.date DESC, t.time DESC
    """, (month+'%',)).fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Transaksi {month}"

    # Header style
    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill("solid", fgColor="1e293b")
    headers = ["Tanggal", "Jam", "Tipe", "Jumlah", "Kategori", "Akun", "Merchant", "Catatan"]

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center")

    # Data
    type_colors = {"income": "22c55e", "expense": "ef4444", "saving": "00d4ff", "invest": "a855f7", "transfer": "f59e0b"}
    for i, r in enumerate(rows, 2):
        ws.cell(row=i, column=1, value=r['date'])
        ws.cell(row=i, column=2, value=r['time'])
        ws.cell(row=i, column=3, value=r['type'])
        amt = ws.cell(row=i, column=4, value=r['amount'])
        amt.number_format = '#,##0'
        ws.cell(row=i, column=5, value=(r['icon'] or '') + ' ' + (r['cat'] or ''))
        ws.cell(row=i, column=6, value=r['acct'] or '')
        ws.cell(row=i, column=7, value=r['merchant'] or '')
        ws.cell(row=i, column=8, value=r['note'] or '')

        # Color by type
        color = type_colors.get(r['type'], '64748b')
        ws.cell(row=i, column=4).font = Font(color=color, bold=True)

    # Auto-width
    for col in range(1, 9):
        max_len = max((len(str(ws.cell(row=r, column=col).value or '')) for r in range(1, len(rows)+2)), default=10)
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = min(max_len + 4, 30)

    # Summary row
    summary_row = len(rows) + 3
    summary = {}
    for r in rows:
        summary[r['type']] = summary.get(r['type'], 0) + r['amount']
    ws.cell(row=summary_row, column=1, value="RINGKASAN").font = Font(bold=True, size=12)
    row = summary_row + 1
    for typ, total in summary.items():
        ws.cell(row=row, column=1, value=f"{typ}:")
        c = ws.cell(row=row, column=2, value=total)
        c.number_format = '#,##0'
        c.font = Font(bold=True, color=type_colors.get(typ, 'ffffff'))
        row += 1

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=finance_{month}.xlsx"}
    )
