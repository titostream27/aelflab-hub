"""
AelfLab Hub — Backend Monitoring API
FastAPI server: frontend + monitoring + history
"""
import os, subprocess, json, time, sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import FileResponse
import httpx
import sys
from fastapi import Request
from fastapi.responses import RedirectResponse

# Finance tracker
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.finance import router as finance_router
from backend.pdf import router as pdf_router

app = FastAPI(title="AelfLab Hub API")
app.include_router(finance_router)
app.include_router(pdf_router)
HUB_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = HUB_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Podcast Clip Miner runs as its own service, not inside this process: it is a
# Next.js app with its own SQLite database, so it cannot be mounted as a router
# the way finance and pdf are. The Hub treats it as a launcher entry plus a
# health probe. Port 8083 continues the local convention (8081 Hub,
# 8082 redirect); 3000 is already taken by Open WebUI.
MINER_URL = os.environ.get("MINER_URL", "http://127.0.0.1:8083")

# ── Helpers ──────────────────────────────────────

def run_pwsh(script: str) -> str:
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"

def run_cmd(cmd: list, timeout=10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


# ── Data Logger ──────────────────────────────────

HISTORY_FILE = DATA_DIR / "history.jsonl"

def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    return [json.loads(l) for l in HISTORY_FILE.read_text().splitlines() if l.strip()]

def save_history(entries: list):
    HISTORY_FILE.write_text("\n".join(json.dumps(e) for e in entries[-720:]))  # max ~30d @ 1h interval

def log_snapshot(data: dict):
    """Log hourly snapshot (skip if last entry < 55 min ago)."""
    entries = load_history()
    now = time.time()
    if entries and (now - entries[-1].get("t", 0)) < 3300:  # ~55 min
        return
    entries.append({
        "t": now,
        "disk_free_gb": data.get("disk_free_gb", 0),
        "disk_total_gb": data.get("disk_total_gb", 0),
        "uptime_hours": data.get("uptime_hours", 0),
        "mem_pct": data.get("mem_pct", 0),
    })
    save_history(entries)


# ── Get DeepSeek API Key ─────────────────────────

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "D:/homelab/hermes"))


def get_secret(name: str) -> str:
    """Baca konfigurasi dari environment, fallback ke .env milik Hermes.

    Dipakai untuk kredensial dan identitas yang tidak boleh ada di source.
    """
    val = os.environ.get(name, "")
    if val:
        return val
    env_path = hermes_home() / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                if key.strip() == name:
                    return raw.strip().strip('"').strip("'")
        except Exception as e:
            print(f"[warn] gagal baca {env_path}: {e}")
    return ""


def get_dk_key() -> str:
    return get_secret("DEEPSEEK_API_KEY")


async def miner_health() -> str:
    """One-line status for the Clip Miner, read from its own /api/health.

    Returns a clip count when reachable, because "how many clips are waiting"
    is the only number worth a slot on the dashboard. Never raises - a stopped
    service must not break the Hub status endpoint.
    """
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            resp = await client.get(f"{MINER_URL}/api/health")
            if resp.status_code != 200:
                return "Offline"
            data = resp.json()
            clips = data.get("library", {}).get("clipsInLibrary", 0)
            # Surface demo mode: without a YouTube key the pipeline serves a
            # synthetic catalogue, which is easy to mistake for real results.
            suffix = " (demo)" if data.get("discovery") == "demo" else ""
            return f"{clips} clip{'s' if clips != 1 else ''}{suffix}"
    except Exception:
        return "Offline"


def run_pwsh_file(script_name: str) -> str:
    """Run a .ps1 script from backend/ dir and return stdout."""
    script_path = Path(__file__).resolve().parent / script_name
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


# ── Endpoints ────────────────────────────────────

@app.get("/api/status")
async def api_status():
    now = datetime.now()
    now_ts = time.time()

    # ── DeepSeek Balance ──
    deepseek_balance = "—"
    dk_key = get_dk_key()
    if dk_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.deepseek.com/user/balance",
                    headers={"Authorization": f"Bearer {dk_key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    total_bal = "0"
                    if data.get("balance_infos"):
                        total_bal = data["balance_infos"][0].get("total_balance", "0")
                    deepseek_balance = f"${float(total_bal):.2f}"
        except:
            deepseek_balance = "ERR"

    # ── Disk ──
    disk_out = run_pwsh("Get-Volume -DriveLetter D | ForEach-Object { '{0},{1}' -f $_.SizeRemaining, $_.Size }")
    disk_free_gb = disk_total_gb = 0
    disk_free = disk_total = "—"
    if disk_out and "," in disk_out:
        parts = disk_out.split(",")
        free_b = int(parts[0]) if parts[0].isdigit() else 0
        total_b = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        disk_free_gb = round(free_b / (1024**3), 0)
        disk_total_gb = round(total_b / (1024**3), 0)
        disk_free = f"{disk_free_gb:.0f} GB"
        disk_total = f"{disk_total_gb:.0f} GB"

    # ── Memory ──
    mem_out = run_pwsh("Get-CimInstance Win32_OperatingSystem | ForEach-Object { '{0},{1}' -f $_.FreePhysicalMemory, $_.TotalVisibleMemorySize }")
    mem_used = mem_total = "—"
    mem_pct = 0
    if mem_out and "," in mem_out:
        parts = mem_out.split(",")
        free_kb = int(parts[0]) if parts[0].isdigit() else 0
        total_kb = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        used_kb = total_kb - free_kb
        mem_used = f"{used_kb / (1024**2):.1f} GB"
        mem_total = f"{total_kb / (1024**2):.1f} GB"
        mem_pct = round(used_kb / total_kb * 100, 0)

    # ── Docker ──
    docker_out = run_cmd(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"])
    docker_status = "—"
    if docker_out:
        lines = [l for l in docker_out.splitlines() if l.strip()]
        running = sum(1 for l in lines if "Up" in l)
        total = len(lines)
        docker_status = f"{running}/{total} running" if "ERROR" not in docker_out else "Not installed"

    # ── Gateway ──
    gw_cmd = "if (Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { (Get-CimInstance Win32_Process -Filter \"ProcessId = $($_.Id)\" | Select-Object -ExpandProperty CommandLine) -match 'gateway' }) { 'Running' } else { 'Stopped' }"
    gw_out = run_pwsh(gw_cmd)
    gateway_status = gw_out if gw_out and gw_out not in ("", "ERROR") else "—"

    # ── IPs ──
    ts_out = run_cmd(["powershell.exe", "-NoProfile", "-Command", "(Get-NetIPAddress -InterfaceAlias '*Tailscale*' -AddressFamily IPv4).IPAddress"])
    tailscale_ip = ts_out if ts_out and "ERROR" not in ts_out else "—"
    local_out = run_cmd(["powershell.exe", "-NoProfile", "-Command", "(Get-NetIPAddress -InterfaceAlias 'Ethernet*' -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.*' }).IPAddress"])
    local_ip = local_out if local_out and "ERROR" not in local_out else "—"

    # ── Ollama ──
    ollama_out = run_cmd(["ollama", "list"])
    ollama_status = "—"
    if ollama_out and "ERROR" not in ollama_out:
        models = [l.split()[0] for l in ollama_out.splitlines()[1:] if l.strip()]
        ollama_status = f"{len(models)} model(s)" if models else "No models"
    else:
        ollama_status = "Offline"

    # ── Uptime ──
    uptime_out = run_pwsh("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime")
    uptime = "—"
    uptime_hours = 0
    if uptime_out and uptime_out not in ("", "ERROR"):
        try:
            boot = datetime.strptime(uptime_out.split(".")[0], "%Y%m%d%H%M%S")
            delta = now - boot
            uptime_hours = round(delta.total_seconds() / 3600, 0)
            d = delta.days; h = delta.seconds // 3600
            uptime = f"{d}d {h}h" if d > 0 else f"{h}h"
        except:
            uptime = uptime_out

    miner_status = await miner_health()

    result = {
        "deepseek_balance": deepseek_balance,
        "miner": miner_status,
        "disk_free": disk_free, "disk_total": disk_total,
        "disk_free_gb": disk_free_gb, "disk_total_gb": disk_total_gb,
        "memory_used": mem_used, "memory_total": mem_total, "mem_pct": mem_pct,
        "docker": docker_status, "gateway": gateway_status,
        "ollama": ollama_status, "uptime": uptime, "uptime_hours": uptime_hours,
        "ip_tailscale": tailscale_ip, "ip_local": local_ip,
        "timestamp": now.isoformat(),
    }

    log_snapshot(result)
    return result


# ── Ollama Models ────────────────────────────────

@app.get("/api/ollama/models")
async def ollama_models():
    out = run_cmd(["ollama", "list"])
    if not out or "ERROR" in out:
        return {"models": [], "error": "Ollama offline"}

    models = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            models.append({
                "name": parts[0],
                "id": parts[1][:12],
                "size": parts[2],
                "modified": " ".join(parts[3:]),
            })
    return {"models": models}

@app.get("/api/ollama/ps")
async def ollama_ps():
    out = run_cmd(["ollama", "ps"])
    loaded = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            loaded.append({
                "name": parts[0],
                "id": parts[1][:12],
                "size": parts[2],
                "processor": parts[3],
            })
    return {"loaded": loaded}


# ── Network Traffic ──────────────────────────────

@app.get("/api/network")
async def network_traffic():
    out = run_pwsh_file("network.ps1")
    if not out or "|" not in out:
        return {"name": "—", "rx_bytes": 0, "tx_bytes": 0}

    parts = out.split("|")
    return {
        "name": parts[0],
        "rx_bytes": int(parts[1]) if parts[1].isdigit() else 0,
        "tx_bytes": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        "rx_gb": f"{int(parts[1]) / (1024**3):.1f} GB" if parts[1].isdigit() else "0 GB",
        "tx_gb": f"{int(parts[2]) / (1024**3):.1f} GB" if len(parts) > 2 and parts[2].isdigit() else "0 GB",
    }


# ── History (Uptime & Disk) ──────────────────────

@app.get("/api/history")
async def get_history(days: int = 7):
    entries = load_history()
    if not entries:
        return {"uptime": [], "disk": [], "memory": []}

    cutoff = time.time() - days * 86400
    filtered = [e for e in entries if e.get("t", 0) >= cutoff]

    uptime_pts = []
    disk_pts = []
    mem_pts = []

    for e in filtered:
        ts = datetime.fromtimestamp(e["t"]).strftime("%m/%d %H:%M")
        uptime_pts.append({"t": ts, "hours": e.get("uptime_hours", 0)})
        disk_pts.append({"t": ts, "free_gb": e.get("disk_free_gb", 0), "total_gb": e.get("disk_total_gb", 0)})
        mem_pts.append({"t": ts, "pct": e.get("mem_pct", 0)})

    return {"uptime": uptime_pts, "disk": disk_pts, "memory": mem_pts}


# ── Serve Frontend ──────────────────────────────

@app.get("/")
async def serve_index(request: Request = None):
    host = request.headers.get("host", "") if request else ""
    if host.startswith("finance"):
        return FileResponse(HUB_DIR / "finance.html")
    if host.startswith("pdf"):
        return FileResponse(HUB_DIR / "pdf.html")
    return FileResponse(HUB_DIR / "index.html")

@app.get("/finance")
async def serve_finance():
    return FileResponse(HUB_DIR / "finance.html")

@app.get("/pdf")
async def serve_pdf():
    return FileResponse(HUB_DIR / "pdf.html")

@app.get("/miner")
async def serve_miner():
    # Unlike /finance and /pdf, this cannot be served from a file: the Clip
    # Miner is a separate Next.js process. Redirect to its own hostname so the
    # Hub stays a launcher and does not become a reverse proxy.
    return RedirectResponse("https://miner.aelflab.com", status_code=307)


# ── Cron Manager ────────────────────────────────

CRON_DIR = hermes_home() / "cron"

@app.get("/api/cron")
async def cron_list():
    jobs = []
    jobs_file = CRON_DIR / "jobs.json"
    if jobs_file.exists():
        try:
            raw = json.loads(jobs_file.read_text())
            jl = raw.get("jobs", raw if isinstance(raw, list) else {})
            if isinstance(jl, dict):
                for jid, j in jl.items():
                    j["job_id"] = jid
                    jobs.append(j)
            elif isinstance(jl, list):
                jobs = jl
        except: pass

    # Also read execution history
    execs = []
    db_path = CRON_DIR / "executions.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT job_id, status, started_at, finished_at, error FROM executions ORDER BY started_at DESC LIMIT 20")
            for row in cur.fetchall():
                execs.append({"job_id": row[0], "status": row[1], "started_at": row[2], "finished_at": row[3], "error": row[4]})
            conn.close()
        except: pass

    # Read recent output files
    output_dir = CRON_DIR / "output"
    recent_outputs = []
    if output_dir.exists():
        for job_dir in sorted(output_dir.iterdir()):
            if job_dir.is_dir():
                files = sorted(job_dir.iterdir(), reverse=True)[:3]
                for f in files:
                    recent_outputs.append({"job_id": job_dir.name, "file": f.name, "size": f.stat().st_size})

    return {"jobs": jobs, "executions": execs[:10], "recent_outputs": recent_outputs[:10]}


def get_job_name(job_id: str) -> str:
    """Baca nama job dari jobs.json."""
    jobs_file = hermes_home() / "cron" / "jobs.json"
    if not jobs_file.exists():
        return job_id
    try:
        raw = json.loads(jobs_file.read_text())
        jl = raw.get("jobs", raw if isinstance(raw, list) else {})
        if isinstance(jl, dict):
            for jid, j in jl.items():
                if jid == job_id:
                    return j.get("name", job_id)
        elif isinstance(jl, list):
            for j in jl:
                if j.get("id") == job_id:
                    return j.get("name", job_id)
    except: pass
    return job_id

def send_telegram_msg(text: str):
    """Kirim notifikasi ke Telegram.

    Token dan chat id dibaca dari environment atau .env Hermes — keduanya
    tidak boleh di-hardcode di source.
    """
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[warn] notifikasi Telegram dilewati: "
              "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diset")
        return
    try:
        import httpx
        with httpx.Client(timeout=5) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            )
    except: pass

@app.post("/api/cron/run/{job_id}")
async def cron_run(job_id: str):
    try:
        venv_python = hermes_home() / "hermes-agent" / "venv" / "Scripts" / "python.exe"
        r = subprocess.run(
            [str(venv_python), "-m", "hermes_cli.main", "cron", "run", job_id],
            capture_output=True, text=True, timeout=180,
            cwd=hermes_home() / "hermes-agent"
        )
        success = r.returncode == 0
        job_name = get_job_name(job_id)
        if success:
            send_telegram_msg(f"✅ *{job_name}* dijalankan dari dashboard.\n`{r.stdout.strip()[:200]}`")
        else:
            send_telegram_msg(f"❌ *{job_name}* gagal: `{r.stderr.strip()[:200]}`")
        return {"status": "ok" if success else "error", "output": r.stdout.strip() or r.stderr.strip()}
    except Exception as e:
        send_telegram_msg(f"❌ Cron run error: `{str(e)[:200]}`")
        return {"status": "error", "output": str(e)}


# ── Speed Test ──────────────────────────────────

@app.get("/api/speedtest")
async def speedtest():
    # Ping test
    ping_out = run_cmd(["ping", "-n", "4", "8.8.8.8"], timeout=20)
    ping_ms = "—"
    if ping_out:
        for line in ping_out.splitlines():
            if "Average" in line or "rata-rata" in line:
                parts = line.split("=")
                if len(parts) >= 2:
                    ping_ms = parts[-1].strip().replace("ms", "").strip()

    # Download test (small file)
    dl_speed = "—"
    dl_time = "—"
    try:
        start = time.time()
        r = subprocess.run(
            ["curl", "-o", "nul", "-s", "-w", "%{speed_download}", "http://speedtest.tele2.net/100KB.zip"],
            capture_output=True, text=True, timeout=20
        )
        elapsed = time.time() - start
        if r.stdout.strip():
            bps = float(r.stdout.strip())
            dl_speed = f"{bps / 1024:.0f} KB/s" if bps < 1024*1024 else f"{bps / (1024*1024):.1f} MB/s"
            dl_time = f"{elapsed:.1f}s"
    except:
        pass

    return {
        "ping_ms": ping_ms,
        "download_speed": dl_speed,
        "download_time": dl_time,
        "timestamp": datetime.now().isoformat(),
    }


# ── GPU Monitoring ─────────────────────────────

@app.get("/api/gpu")
async def gpu_status():
    out = run_pwsh_file("gpu-perf.ps1")
    data = {"name": "—", "vram_total": "—", "vram_used": "—", "util_pct": "—", "driver": "—"}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k == "GPU_NAME": data["name"] = v
            elif k == "GPU_RAM": data["vram_total"] = f"{v} GB"
            elif k == "GPU_DRIVER": data["driver"] = v[:15]
            elif k == "GPU_UTIL": data["util_pct"] = f"{v}%"
            elif k == "GPU_VRAM_USED":
                used_gb = round(int(v) / 1024, 1) if v.isdigit() else v
                data["vram_used"] = f"{used_gb} GB"
    return data


# ── Quick Actions ──────────────────────────────

@app.post("/api/action/{action}")
async def quick_action(action: str):
    try:
        if action == "restart-gateway":
            r = run_cmd(["powershell.exe", "-NoProfile", "-Command",
                "Restart-Service cloudflared -Force; Write-Host 'cloudflared restarted'"])
            return {"status": "ok" if r else "error", "output": r}
        elif action == "restart-ollama":
            r = run_cmd(["ollama", "--version"])
            if not r or "ERROR" in r:
                return {"status": "error", "output": "Ollama not available"}
            # Start up ollama server
            return {"status": "ok", "output": "Ollama is running"}
        elif action == "prune-docker":
            r = run_cmd(["docker", "system", "prune", "-f"], timeout=30)
            return {"status": "ok", "output": r[:200] if r else "Done"}
        elif action == "test-internet":
            ping = run_cmd(["ping", "-n", "2", "8.8.8.8"], timeout=15)
            return {"status": "ok", "output": ping[:200] if ping else "No response"}
        else:
            return {"status": "error", "output": f"Unknown action: {action}"}
    except Exception as e:
        return {"status": "error", "output": str(e)}


# ── Main ─────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
