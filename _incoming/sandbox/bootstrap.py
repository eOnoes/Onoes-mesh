# bootstrap.py — writes the mesh-system-dashboard preview folder. Stdlib only.
# Run:  python bootstrap.py D:/Dev/Onoes-Mesh-sandbox/mesh-system-dashboard
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "./mesh-system-dashboard").resolve()
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "data").mkdir(exist_ok=True)

FILES = {}

FILES["system_dashboard.py"] = r'''
from __future__ import annotations
import csv, http.client, json, os, shutil, sqlite3, threading, time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB_PATH = DATA / "system_dashboard.db"
PREFS_PATH = DATA / "system_dashboard_prefs.json"
DEFAULT_PREFS = {"theme": "dark"}
_DB_LOCK = threading.Lock()
_last_persist = 0.0

ENGINE_ADAPTERS = [
    {"engine": "strata", "host": "127.0.0.1", "port": 8094,
     "health_path": "/health", "models_path": "/v1/models",
     "webapp_url": "http://127.0.0.1:8094/"}
]

def _iso(ts=None):
    try:
        return datetime.fromtimestamp(float(ts if ts is not None else time.time()), tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

def subprocess_run(cmd, **kw):
    import subprocess
    return subprocess.run(cmd, **kw)

def _run(cmd, timeout=3.0):
    kw = {"capture_output": True, "text": True, "timeout": timeout}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000
    try:
        p = subprocess_run(cmd, **kw)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    except Exception as exc:
        return None, "", str(exc)[:300]

def _parse_float(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.upper() in {"N/A", "N/A N/A", "NA"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None

def get_gpu_metrics():
    rc, out, err = _run(["nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.total,memory.used,memory.free,power.draw,fan.speed",
        "--format=csv,noheader,nounits"], timeout=3.0)
    if rc != 0 or not out.strip():
        return {"available": False, "source": "nvidia-smi",
                "reason": (err or "nvidia-smi unavailable").strip()[:300], "gpus": [], "gpu": {}}
    gpus = []
    for line in out.strip().splitlines():
        try:
            parts = next(csv.reader([line]))
        except Exception:
            continue
        if len(parts) < 9:
            continue
        vt = _parse_float(parts[4]); vu = _parse_float(parts[5]); vf = _parse_float(parts[6])
        vp = round((vu / vt) * 100, 1) if (vu is not None and vt) else None
        gpus.append({"name": parts[0].strip(),
            "temperature_c": _parse_float(parts[1]),
            "utilization_gpu_percent": _parse_float(parts[2]),
            "utilization_memory_percent": _parse_float(parts[3]),
            "vram_total_mib": vt, "vram_used_mib": vu, "vram_free_mib": vf,
            "vram_total_bytes": int(vt*1024*1024) if vt is not None else None,
            "vram_used_bytes": int(vu*1024*1024) if vu is not None else None,
            "vram_free_bytes": int(vf*1024*1024) if vf is not None else None,
            "vram_percent": vp,
            "power_w": _parse_float(parts[7]), "fan_percent": _parse_float(parts[8])})
    if not gpus:
        return {"available": False, "source": "nvidia-smi", "reason": "unexpected nvidia-smi output", "gpus": [], "gpu": {}}
    return {"available": True, "source": "nvidia-smi", "gpus": gpus, "gpu": gpus[0]}

def get_cpu_metrics():
    return {"available": False, "temperature_c": None, "fan_percent": None,
            "fan_rpm": None, "power_w": None,
            "reason": "No verified CPU sensor source configured for Phase 1"}

def get_memory_metrics():
    if os.name != "nt":
        return {"available": False, "reason": "stdlib memory probe currently targets Windows"}
    import ctypes
    class M(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    s = M(); s.dwLength = ctypes.sizeof(M)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    except Exception as exc:
        return {"available": False, "reason": str(exc)[:300]}
    if not ok:
        return {"available": False, "reason": "GlobalMemoryStatusEx failed"}
    total = int(s.ullTotalPhys); avail = int(s.ullAvailPhys); used = total - avail
    return {"available": True, "source": "windows_kernel32", "total_bytes": total,
            "available_bytes": avail, "used_bytes": used,
            "percent_used": round((used/total)*100, 1) if total else None}

_DRIVE_TYPE_NAMES = {0:"unknown",1:"no-root",2:"removable",3:"local",4:"network",5:"cdrom",6:"ramdisk"}
def _drive_type(letter):
    if os.name != "nt":
        return "unknown"
    import ctypes
    try:
        dt = ctypes.windll.kernel32.GetDriveTypeW(letter + ":\\")
    except Exception:
        return "unknown"
    return _DRIVE_TYPE_NAMES.get(int(dt), "unknown")

def get_drive_metrics():
    drives = []
    for letter in ("C", "D"):
        dtype = _drive_type(letter)
        if dtype != "local":
            drives.append({"letter": letter, "available": False, "type": dtype, "reason": "not a local fixed drive"})
            continue
        try:
            total, used, free = shutil.disk_usage(letter + ":\\")
        except Exception as exc:
            drives.append({"letter": letter, "available": False, "type": dtype, "reason": str(exc)[:300]})
            continue
        drives.append({"letter": letter, "available": True, "type": dtype,
            "total_bytes": int(total), "used_bytes": int(used), "free_bytes": int(free),
            "percent_used": round((used/total)*100, 1) if total else None})
    return drives

def _http_get_json(host, port, path, timeout=2.0):
    if host not in {"127.0.0.1", "localhost"}:
        return False, {"reason": "non-loopback endpoint disabled"}
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path, headers={"Accept": "application/json", "Host": host + ":" + str(port)})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        if resp.status >= 400:
            return False, {"status": resp.status, "reason": "HTTP " + str(resp.status)}
        try:
            return True, json.loads(raw.decode("utf-8"))
        except Exception:
            return False, {"status": resp.status, "reason": "non-JSON response"}
    except Exception as exc:
        return False, {"reason": str(exc)[:300]}

def _models_list(models):
    if isinstance(models, dict):
        arr = models.get("data") or models.get("models") or []
    elif isinstance(models, list):
        arr = models
    else:
        arr = []
    if not isinstance(arr, list):
        return []
    out = []
    for item in arr:
        mid = (item.get("id") or item.get("name") or item.get("model")) if isinstance(item, dict) else (item if isinstance(item, str) else None)
        if mid:
            out.append(str(mid))
    return out

def discover_llms():
    records = []
    for a in ENGINE_ADAPTERS:
        host, port = a["host"], int(a["port"])
        hp, mp = a["health_path"], a["models_path"]
        endpoint = "http://" + host + ":" + str(port)
        ok_h, health = _http_get_json(host, port, hp)
        ok_m, models = _http_get_json(host, port, mp)
        if not ok_h and not ok_m:
            reason = (health.get("reason") if isinstance(health, dict) else None) or (models.get("reason") if isinstance(models, dict) else None) or "unreachable"
            records.append({"engine": a["engine"], "status": "unavailable", "reason": reason,
                "endpoint": endpoint, "health_endpoint": endpoint+hp, "models_endpoint": endpoint+mp,
                "webapp_url": a.get("webapp_url"), "model_id": None, "model_ids": [],
                "context": None, "version": None, "evidence": [],
                "controls": {"pause": False, "unload": False, "stop": False}})
            continue
        mids = _models_list(models) if ok_m else []
        evidence = (["health"] if ok_h else []) + (["models"] if ok_m else [])
        status = "detected"
        if ok_h and isinstance(health, dict):
            if health.get("loaded") is True or str(health.get("status","")).lower() in {"loaded","running","active"}:
                status = "loaded"; evidence.append("health-loaded")
        context = version = None
        if ok_h and isinstance(health, dict):
            for k in ("context","context_length","max_context","context_window","ctx"):
                if health.get(k) is not None:
                    try: context = int(health[k])
                    except Exception: pass
                    break
            version = health.get("version") or health.get("engine_version") or health.get("build")
        records.append({"engine": a["engine"], "status": status, "reason": None,
            "endpoint": endpoint, "health_endpoint": endpoint+hp, "models_endpoint": endpoint+mp,
            "webapp_url": a.get("webapp_url"), "model_id": (mids[0] if mids else None), "model_ids": mids,
            "context": context, "version": version, "evidence": evidence,
            "controls": {"pause": False, "unload": False, "stop": False}})
    return records

def collect_state():
    now = time.time(); g = _iso(now)
    return {"ok": True, "version": VERSION, "generated_at": g,
        "metrics": {"generated_at": g, "gpu": get_gpu_metrics(), "cpu": get_cpu_metrics(),
                    "memory": get_memory_metrics(), "drives": get_drive_metrics()},
        "llm": discover_llms()}

def collect_and_persist():
    global _last_persist
    state = collect_state()
    now = time.time()
    if now - _last_persist >= 2.0:
        try: persist_sample(state)
        except Exception: pass
        _last_persist = now
    return state

def snapshot(path):
    if path == "/api/system/health":
        return {"ok": True, "module": "system_dashboard", "version": VERSION, "phase": "read-only", "generated_at": _iso()}
    if path == "/api/system/prefs":
        return load_prefs()
    state = collect_state()
    if path == "/api/system/metrics": return state["metrics"]
    if path == "/api/system/llm": return state["llm"]
    if path == "/api/system/drives": return state["metrics"]["drives"]
    return state

def load_prefs():
    try:
        if PREFS_PATH.exists():
            d = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("theme") in {"dark","light"}:
                return {"theme": d["theme"]}
    except Exception:
        pass
    return DEFAULT_PREFS.copy()

def save_prefs(theme, atomic_json):
    if theme not in {"dark","light"}:
        raise ValueError("Invalid theme")
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(PREFS_PATH, {"theme": theme})

def render_index_with_theme(index_path):
    theme = load_prefs().get("theme","dark")
    html = index_path.read_bytes()
    if b"data-theme=" in html: return html
    if b"<html " in html:
        return html.replace(b"<html ", b'<html data-theme="' + theme.encode("utf-8") + b'" ', 1)
    if b"<html>" in html:
        return html.replace(b"<html>", b'<html data-theme="' + theme.encode("utf-8") + b'>', 1)
    return html

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20); db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try: db.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError: db.execute("PRAGMA journal_mode = DELETE")
    schema = ("CREATE TABLE IF NOT EXISTS system_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
      "gpu_name TEXT, gpu_temp REAL, gpu_util REAL, gpu_fan REAL, gpu_power REAL, "
      "vram_used_bytes REAL, vram_total_bytes REAL, vram_percent REAL, "
      "cpu_temp REAL, cpu_fan REAL, cpu_power REAL, "
      "ram_percent REAL, ram_used_bytes REAL, ram_total_bytes REAL, "
      "c_percent REAL, c_free_bytes REAL, d_percent REAL, d_free_bytes REAL, json TEXT); "
      "CREATE TABLE IF NOT EXISTS system_llm_state (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, json TEXT NOT NULL); "
      "CREATE TABLE IF NOT EXISTS system_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, severity TEXT, code TEXT, message TEXT, json TEXT); "
      "CREATE TABLE IF NOT EXISTS system_control_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, engine TEXT, model TEXT, method TEXT, identity_evidence TEXT, result TEXT, reason TEXT, json TEXT); "
      "CREATE INDEX IF NOT EXISTS idx_system_metrics_ts ON system_metrics(ts); "
      "CREATE INDEX IF NOT EXISTS idx_system_llm_state_ts ON system_llm_state(ts);")
    db.executescript(schema)
    return db

def _find_drive(drives, letter):
    for d in drives:
        if d.get("letter") == letter: return d
    return {}

def persist_sample(state):
    if not isinstance(state, dict): return
    with _DB_LOCK:
        db = _connect()
        try:
            now = int(time.time())
            m = state.get("metrics") or {}
            gpu = m.get("gpu") or {}; fg = gpu.get("gpu") if isinstance(gpu, dict) else {}
            cpu = m.get("cpu") or {}; mem = m.get("memory") or {}; dr = m.get("drives") or []
            c = _find_drive(dr, "C"); d = _find_drive(dr, "D")
            db.execute("INSERT INTO system_metrics (ts,gpu_name,gpu_temp,gpu_util,gpu_fan,gpu_power,vram_used_bytes,vram_total_bytes,vram_percent,cpu_temp,cpu_fan,cpu_power,ram_percent,ram_used_bytes,ram_total_bytes,c_percent,c_free_bytes,d_percent,d_free_bytes,json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, fg.get("name"), fg.get("temperature_c"), fg.get("utilization_gpu_percent"), fg.get("fan_percent"), fg.get("power_w"), fg.get("vram_used_bytes"), fg.get("vram_total_bytes"), fg.get("vram_percent"), cpu.get("temperature_c"), cpu.get("fan_percent"), cpu.get("power_w"), mem.get("percent_used"), mem.get("used_bytes"), mem.get("total_bytes"), c.get("percent_used"), c.get("free_bytes"), d.get("percent_used"), d.get("free_bytes"), json.dumps(m, ensure_ascii=False)))
            db.execute("INSERT INTO system_llm_state (ts, json) VALUES (?, ?)", (now, json.dumps(state.get("llm") or [], ensure_ascii=False)))
            cutoff = now - 7200
            db.execute("DELETE FROM system_metrics WHERE ts < ?", (cutoff,))
            db.execute("DELETE FROM system_metrics WHERE id NOT IN (SELECT id FROM system_metrics ORDER BY ts DESC LIMIT 3600)")
            db.execute("DELETE FROM system_llm_state WHERE ts < ?", (cutoff,))
            db.execute("DELETE FROM system_llm_state WHERE id NOT IN (SELECT id FROM system_llm_state ORDER BY ts DESC LIMIT 3600)")
            db.commit()
        finally:
            db.close()
'''

FILES["server.py"] = r'''
from __future__ import annotations
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import system_dashboard

ROOT = Path(__file__).resolve().parent
SERVICE_TAG = "mesh-system"; SERVICE_ROLE = "monitor"
DEFAULT_PORT = 8780
ALLOWED_HOSTS = {"127.0.0.1:" + str(DEFAULT_PORT)}
ALLOWED_ORIGINS = {"http://127.0.0.1:" + str(DEFAULT_PORT)}
SYSTEM_SSE_SLOTS = threading.Semaphore(4)
SYSTEM_SSE_HEARTBEAT_SECONDS = 15
SYSTEM_SSE_WAIT_SECONDS = 2
SYSTEM_SSE_MAX_SECONDS = 1800

def atomic_json(path, value):
    temp = path.with_suffix(".json.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as s:
            json.dump(value, s, ensure_ascii=False, indent=2); s.write("\n"); s.flush(); os.fsync(s.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): return
    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else payload
        self.send_response(status); self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Mesh-Service", SERVICE_TAG); self.send_header("X-Mesh-Role", SERVICE_ROLE)
        self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers(); self.wfile.write(body)
    def _sse_field(self, name, value):
        for line in str(value).split("\n"): self.wfile.write((name + ": " + line + "\n").encode("utf-8"))
    def _sse_comment(self, text): self.wfile.write((": " + text + "\n\n").encode("utf-8"))
    def _sse_flush(self): self.wfile.flush()
    def local_request(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in ALLOWED_HOSTS:
            self.reply(403, {"error": "Use http://127.0.0.1:" + str(DEFAULT_PORT) + "/"}); return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] not in ALLOWED_ORIGINS):
            self.reply(403, {"error": "Local page requests only."}); return False
        return True
    def system_stream(self):
        if not SYSTEM_SSE_SLOTS.acquire(blocking=False):
            self.reply(429, {"error": "Too many system streams."}); return
        started = time.time()
        try:
            self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close"); self.end_headers()
            self._sse_field("retry", 2000); self.wfile.write(b"\n"); self._sse_flush()
            self._sse_comment("system stream open"); self._sse_flush()
            last_beat = time.time()
            while time.time() - started < SYSTEM_SSE_MAX_SECONDS:
                state = system_dashboard.collect_and_persist()
                self._sse_field("data", json.dumps(state, ensure_ascii=False)); self.wfile.write(b"\n"); self._sse_flush()
                until = time.time() + SYSTEM_SSE_WAIT_SECONDS
                while time.time() < until:
                    if time.time() - last_beat >= SYSTEM_SSE_HEARTBEAT_SECONDS:
                        self._sse_comment("heartbeat"); self._sse_flush(); last_beat = time.time()
                    time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            SYSTEM_SSE_SLOTS.release()
    def do_GET(self):
        if not self.local_request(): return
        path = self.path.split("?", 1)[0]
        if path == "/system":
            self.reply(200, system_dashboard.render_index_with_theme(ROOT / "index.html"), "text/html; charset=utf-8"); return
        if path == "/api/system/events":
            self.system_stream(); return
        if path in {"/api/system/health","/api/system/metrics","/api/system/llm","/api/system/drives","/api/system/prefs"}:
            self.reply(200, system_dashboard.snapshot(path)); return
        routes = {"/": ("index.html","text/html; charset=utf-8"), "/app.js": ("app.js","text/javascript; charset=utf-8")}
        if path == "/favicon.ico":
            self.reply(204, b"", "image/x-icon")
        elif path in routes:
            name, mime = routes[path]; body = (ROOT / name).read_bytes()
            if path == "/" and name == "index.html": body = system_dashboard.render_index_with_theme(ROOT / name)
            self.reply(200, body, mime)
        else:
            self.reply(404, {"error": "Not found."})
    def do_POST(self):
        if not self.local_request(): return
        path = self.path.split("?", 1)[0]
        if path == "/api/system/prefs":
            try: length = int(self.headers.get("Content-Length", "0") or 0)
            except Exception: length = -1
            if length <= 0 or length > 4096:
                self.reply(400, {"error": "Prefs body must be small JSON."}); return
            raw = self.rfile.read(length)
            try: data = json.loads(raw.decode("utf-8"))
            except Exception:
                self.reply(400, {"error": "Invalid JSON."}); return
            if not isinstance(data, dict) or set(data.keys()) != {"theme"} or data["theme"] not in {"dark","light"}:
                self.reply(400, {"error": "Only theme=dark or theme=light is accepted."}); return
            system_dashboard.save_prefs(data["theme"], atomic_json)
            self.reply(200, {"ok": True, "theme": data["theme"]}); return
        self.reply(404, {"error": "Not found."})

def runtime_options(argv):
    port = DEFAULT_PORT
    if len(argv) > 1:
        try: port = int(argv[1])
        except ValueError: raise SystemExit("Port must be a number.")
    if not 1024 <= port <= 65535: raise SystemExit("Use a local port from 1024 to 65535.")
    return port

if __name__ == "__main__":
    port = runtime_options(sys.argv)
    ALLOWED_HOSTS.add("127.0.0.1:" + str(port)); ALLOWED_ORIGINS.add("http://127.0.0.1:" + str(port))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Mesh System Monitor at http://127.0.0.1:" + str(port) + "/#system — read-only.", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
'''

FILES["index.html"] = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<title>Mesh · system</title>
<style>
:root { --bg:#0d0d0f; --surface:#161618; --line:#2a2a2e; --text:#f2f2f2; --muted:#9a9aa3; --dim:#6e6e76;
  --you:#7ec8ff; --agent:#e0a15a; --ok:#3f9d72; --wait:#e0a15a; --pin:#e0c36a; --off:#8a8a8a;
  --lime:#39ff14; --cyan:#3ddcff; --bracket:#e6c200; --stop:#d64545; color-scheme:dark; }
html[data-theme="light"] { --bg:#f0f1f3; --surface:#f8f9fa; --surface-raised:#ffffff; --surface-active:#e8ebef;
  --line:#c8ccd2; --line-strong:#9ea5ae; --text:#1a1c20; --muted:#555b64; --dim:#777e88;
  --you:#056b9c; --agent:#4b5058; --ok:#208a16; --wait:#9a6500; --pin:#856d00; --off:#777e88;
  --lime:#208a16; --cyan:#007da8; --bracket:#856d00; --stop:#b32626; color-scheme:light; }
* { box-sizing:border-box; }
html, body { margin:0; height:100%; }
body { background:var(--bg); color:var(--text); font-family:"Segoe UI", system-ui, sans-serif; overflow:hidden; }
.column { max-width:720px; margin:0 auto; min-width:0; height:100vh; display:flex; flex-direction:column; padding:0 12px; }
.head { display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid var(--line); }
.head .word { background:transparent; border:1px solid var(--line); color:var(--cyan); font-family:"Cascadia Mono", Consolas, monospace; padding:8px 10px; cursor:pointer; }
.head h1 { font-size:15px; font-weight:600; margin:0; flex:1; }
.head .prompt { color:var(--cyan); }
.head .caret { display:inline-block; width:8px; height:14px; background:var(--cyan); margin-left:4px; vertical-align:middle; }
main { flex:1; overflow:auto; padding:12px 0; }
.meta { color:var(--muted); font-size:13px; }
#system-grid { display:grid; gap:10px; width:100%; max-width:100%; }
.system-card { border:1px solid var(--line); background:var(--surface); padding:10px; }
.system-card h2 { margin:0 0 8px; font-family:"Cascadia Mono", Consolas, monospace; font-size:12px; font-weight:600; color:var(--dim); }
.system-row { display:flex; justify-content:space-between; gap:10px; margin:4px 0; font-family:"Cascadia Mono", Consolas, monospace; font-size:13px; overflow-wrap:anywhere; }
.system-row span:first-child { color:var(--muted); }
.system-value { font-family:"Cascadia Mono", Consolas, monospace; overflow-wrap:anywhere; }
.system-actions { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
.system-action { min-height:44px; padding:8px 10px; border:1px solid var(--line); background:var(--surface); color:var(--cyan); font-family:"Cascadia Mono", Consolas, monospace; cursor:pointer; }
.system-action:hover { background:var(--surface-active); }
.system-action:focus-visible { outline:2px solid var(--cyan); outline-offset:2px; }
.system-status-loaded { color:var(--lime); }
.system-status-detected { color:var(--cyan); }
.system-status-unavailable { color:var(--dim); }
.system-llm-item { border-top:1px solid var(--line); padding-top:8px; margin-top:8px; }
.system-llm-item:first-child { border-top:0; padding-top:0; margin-top:0; }
.system-llm-line { display:flex; justify-content:space-between; gap:10px; margin:4px 0; font-family:"Cascadia Mono", Consolas, monospace; font-size:13px; overflow-wrap:anywhere; }
.system-llm-line span:first-child { color:var(--muted); }
.system-llm-actions { margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; }
@media (max-width:520px) { .system-row, .system-llm-line { flex-direction:column; gap:2px; } }
</style>
</head>
<body>
<div class="column">
  <div class="head">
    <button class="word" id="open-menu" type="button" aria-label="Open sections"><span class="br">[</span>nav<span class="br">]</span></button>
    <h1><span class="prompt">&gt;</span> <span id="crumb">system</span><span class="caret"></span></h1>
  </div>
  <main id="pages">
    <section class="page" id="page-system" aria-labelledby="nav-system" hidden>
      <p class="meta" id="system-status">Reading this PC.</p>
      <div class="system-actions">
        <button id="system-refresh" class="system-action" type="button">[ refresh ]</button>
        <button id="system-theme-toggle" class="system-action" type="button">[ ☾ dark ]</button>
      </div>
      <div id="system-grid"></div>
    </section>
  </main>
</div>
<script src="/app.js?v=20261016-system1"></script>
</body>
</html>'''

FILES["app.js"] = r'''
let systemEventSource = null;
const ui = { section: 'system' };
function $(id) { return document.getElementById(id); }
function systemBytes(value) {
  if (value === null || value === undefined) return "unavailable";
  const n = Number(value);
  if (!Number.isFinite(n)) return "unavailable";
  const units = ["B","KiB","MiB","GiB","TiB","PiB"];
  let current = n, unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) { current /= 1024; unitIndex += 1; }
  return unitIndex === 0 ? Math.round(current) + " " + units[unitIndex] : current.toFixed(1) + " " + units[unitIndex];
}
function systemPercent(v) { return (v === null || v === undefined) ? "unavailable" : Number(v).toFixed(1) + "%"; }
function systemTemp(v) { return (v === null || v === undefined) ? "unavailable" : Number(v).toFixed(1) + "°C"; }
function systemWatts(v) { return (v === null || v === undefined) ? "unavailable" : Number(v).toFixed(1) + "W"; }
function systemText(v) { return (v === null || v === undefined || v === "") ? "unavailable" : String(v); }
function systemStatusClass(status) {
  const value = String(status || "").toLowerCase();
  if (value === "loaded") return "system-status-loaded";
  if (value === "detected") return "system-status-detected";
  if (value === "unavailable") return "system-status-unavailable";
  return "";
}
function systemCard(title, rows) {
  const card = document.createElement("div"); card.className = "system-card";
  const heading = document.createElement("h2"); heading.textContent = title; card.appendChild(heading);
  for (const [label, value, className] of rows) {
    const row = document.createElement("div"); row.className = "system-row";
    const labelEl = document.createElement("span"); labelEl.textContent = label;
    const valueEl = document.createElement("span"); valueEl.className = "system-value " + (className || ""); valueEl.textContent = value;
    row.appendChild(labelEl); row.appendChild(valueEl); card.appendChild(row);
  }
  return card;
}
function systemGpuRows(gpu) {
  return [["name", systemText(gpu.name)], ["temp", systemTemp(gpu.temperature_c)],
    ["util", systemPercent(gpu.utilization_gpu_percent)], ["fan", systemPercent(gpu.fan_percent)],
    ["power", systemWatts(gpu.power_w)],
    ["vram", systemPercent(gpu.vram_percent) + " " + systemBytes(gpu.vram_used_bytes) + " / " + systemBytes(gpu.vram_total_bytes)]];
}
function systemMemoryRows(memory) {
  if (!memory.available) return [["ram", "unavailable", "system-status-unavailable"]];
  return [["ram", systemPercent(memory.percent_used) + " " + systemBytes(memory.used_bytes) + " / " + systemBytes(memory.total_bytes)]];
}
function systemDriveRows(drives) {
  if (!drives.length) return [["drives", "unavailable", "system-status-unavailable"]];
  return drives.map((drive) => {
    if (!drive.available) return [drive.letter || "?", "unavailable", "system-status-unavailable"];
    return [drive.letter || "?", systemPercent(drive.percent_used) + " free " + systemBytes(drive.free_bytes) + " / " + systemBytes(drive.total_bytes)];
  });
}
function renderSystem(state) {
  const grid = $("system-grid"); if (!grid) return;
  grid.innerHTML = "";
  const status = $("system-status");
  if (status) {
    let updated = "";
    if (state.generated_at) { try { updated = " Updated " + new Date(state.generated_at).toLocaleTimeString(); } catch (_) { updated = ""; } }
    status.textContent = "Reading this PC." + updated;
  }
  const metrics = state.metrics || {};
  const gpu = metrics.gpu || {}; const cpu = metrics.cpu || {}; const memory = metrics.memory || {}; const drives = metrics.drives || [];
  if (!gpu.available) {
    grid.appendChild(systemCard("GPU", [["status", "unavailable", "system-status-unavailable"]]));
  } else {
    const gpuList = (gpu.gpus && gpu.gpus.length) ? gpu.gpus : [gpu.gpu || {}];
    for (const c of gpuList) grid.appendChild(systemCard(c.name || "GPU", systemGpuRows(c)));
  }
  grid.appendChild(systemCard("CPU / MEMORY", [
    ["cpu temp", systemTemp(cpu.temperature_c), cpu.available ? "" : "system-status-unavailable"],
    ["cpu fan", systemPercent(cpu.fan_percent), cpu.available ? "" : "system-status-unavailable"],
    ["cpu power", systemWatts(cpu.power_w), cpu.available ? "" : "system-status-unavailable"],
    ...systemMemoryRows(memory)]));
  grid.appendChild(systemCard("DRIVES", systemDriveRows(drives)));
  const llmCard = document.createElement("div"); llmCard.className = "system-card";
  const llmHeading = document.createElement("h2"); llmHeading.textContent = "LOCAL LLM"; llmCard.appendChild(llmHeading);
  const items = state.llm || [];
  if (!items.length) { const empty = document.createElement("div"); empty.className = "system-value"; empty.textContent = "no detected engines"; llmCard.appendChild(empty); }
  for (const item of items) {
    const itemDiv = document.createElement("div"); itemDiv.className = "system-llm-item";
    const engineLine = document.createElement("div"); engineLine.className = "system-llm-line";
    const engineLabel = document.createElement("span"); engineLabel.textContent = item.engine || "unknown";
    const statusEl = document.createElement("span"); statusEl.className = systemStatusClass(item.status); statusEl.textContent = systemText(item.status);
    engineLine.appendChild(engineLabel); engineLine.appendChild(statusEl); itemDiv.appendChild(engineLine);
    for (const [label, value] of [
      ["model", systemText(item.model_id)], ["endpoint", systemText(item.endpoint)],
      ["context", item.context ? String(item.context) : "unavailable"], ["version", systemText(item.version)],
      ["evidence", (item.evidence || []).join(", ") || "none"]]) {
      const row = document.createElement("div"); row.className = "system-llm-line";
      const labelEl = document.createElement("span"); labelEl.textContent = label;
      const valueEl = document.createElement("span"); valueEl.className = "system-value"; valueEl.textContent = value;
      row.appendChild(labelEl); row.appendChild(valueEl); itemDiv.appendChild(row);
    }
    if (item.webapp_url) {
      const actions = document.createElement("div"); actions.className = "system-llm-actions";
      const link = document.createElement("a"); link.className = "system-action"; link.href = item.webapp_url;
      link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "[ open " + (item.engine || "engine") + " WebApp ]";
      actions.appendChild(link); itemDiv.appendChild(actions);
    }
    llmCard.appendChild(itemDiv);
  }
  grid.appendChild(llmCard);
}
function startSystem() {
  stopSystem();
  systemEventSource = new EventSource("/api/system/events");
  systemEventSource.onmessage = (event) => {
    try { renderSystem(JSON.parse(event.data)); }
    catch (_) { const s = $("system-status"); if (s) s.textContent = "Bad system stream frame."; }
  };
  systemEventSource.onerror = () => {
    stopSystem();
    const s = $("system-status"); if (s) s.textContent = "System stream disconnected. Reconnecting.";
    setTimeout(() => { if (ui.section === "system") startSystem(); }, 2000);
  };
}
function stopSystem() {
  if (!systemEventSource) return;
  try { systemEventSource.close(); } catch (_) {}
  systemEventSource = null;
}
function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("mesh-theme", next); } catch (_) {}
  const button = $("system-theme-toggle");
  if (button) button.textContent = next === "light" ? "[ ☀ light ]" : "[ ☾ dark ]";
}
function initSystemTheme() {
  let saved = null;
  try { saved = localStorage.getItem("mesh-theme"); } catch (_) {}
  applyTheme(saved === "light" ? "light" : (document.documentElement.dataset.theme || "dark"));
  fetch("/api/system/prefs").then((r) => (r.ok ? r.json() : null)).then((p) => { if (p && p.theme) applyTheme(p.theme); }).catch(() => {});
  const button = $("system-theme-toggle");
  if (button) {
    button.addEventListener("click", async () => {
      const next = (document.documentElement.dataset.theme || "dark") === "light" ? "dark" : "light";
      applyTheme(next);
      try { await fetch("/api/system/prefs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme: next }) }); } catch (_) {}
    });
  }
}
function initSystemControls() {
  const refresh = $("system-refresh");
  if (refresh) refresh.addEventListener("click", () => startSystem());
}
function showSection(section) {
  ui.section = section;
  document.querySelectorAll(".page").forEach((page) => { page.hidden = page.id !== "page-" + section; });
  const crumb = $("crumb"); if (crumb) crumb.textContent = section;
  document.title = "Mesh · " + section;
  if (section === "system") startSystem(); else stopSystem();
}
initSystemTheme();
initSystemControls();
showSection(location.hash.slice(1) || "system");
window.addEventListener("hashchange", () => showSection(location.hash.slice(1) || "system"));
'''

FILES["test_system_dashboard.py"] = r'''
import json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest import mock
import system_dashboard as sd

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as s:
            json.dump(value, s, ensure_ascii=False, indent=2); s.write("\n"); s.flush()
        path.unlink(missing_ok=True); temp.replace(path)
    finally:
        if temp.exists(): temp.unlink()

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        sd.DB_PATH = self.root / "system_dashboard.db"; sd.PREFS_PATH = self.root / "system_dashboard_prefs.json"
    def tearDown(self): self.tmp.cleanup()
    def test_health(self):
        d = sd.snapshot("/api/system/health")
        self.assertTrue(d["ok"]); self.assertEqual(d["module"], "system_dashboard"); self.assertEqual(d["phase"], "read-only")
    def test_gpu_fail(self):
        with mock.patch.object(sd, "_run", return_value=(None, "", "missing")):
            g = sd.get_gpu_metrics()
        self.assertFalse(g["available"]); self.assertEqual(g["reason"], "missing")
    def test_gpu_ok(self):
        s = "NVIDIA GeForce RTX 4080 SUPER, 32, 0, 17, 32760, 1148, 31218, 19.77, 41"
        with mock.patch.object(sd, "_run", return_value=(0, s + "\n", "")):
            g = sd.get_gpu_metrics()
        self.assertTrue(g["available"]); self.assertEqual(g["gpu"]["temperature_c"], 32); self.assertEqual(g["gpu"]["fan_percent"], 41)
    def test_cpu_unavailable(self):
        c = sd.get_cpu_metrics(); self.assertFalse(c["available"]); self.assertIsNone(c["temperature_c"])
    def test_non_loopback(self):
        ok, d = sd._http_get_json("8.8.8.8", 80, "/"); self.assertFalse(ok); self.assertEqual(d["reason"], "non-loopback endpoint disabled")
    def test_strata_down(self):
        with mock.patch.object(sd, "_http_get_json", return_value=(False, {"reason": "connection refused"})):
            l = sd.discover_llms()
        self.assertEqual(l[0]["status"], "unavailable"); self.assertIsNone(l[0]["model_id"]); self.assertEqual(l[0]["reason"], "connection refused")
        self.assertFalse(l[0]["controls"]["pause"]); self.assertFalse(l[0]["controls"]["unload"]); self.assertFalse(l[0]["controls"]["stop"])
    def test_strata_loaded(self):
        def fake(host, port, path, timeout=2.0):
            if path == "/health": return True, {"status": "loaded", "loaded": True, "version": "0.1.44.1", "context": 196608}
            return True, {"data": [{"id": "qwen3.8-flash-next-iq3-s-strata"}]}
        with mock.patch.object(sd, "_http_get_json", side_effect=fake):
            l = sd.discover_llms()
        self.assertEqual(l[0]["status"], "loaded"); self.assertEqual(l[0]["model_id"], "qwen3.8-flash-next-iq3-s-strata"); self.assertEqual(l[0]["context"], 196608)
    def test_prefs(self):
        sd.save_prefs("light", atomic_json); self.assertEqual(sd.load_prefs()["theme"], "light"); self.assertEqual(sd.snapshot("/api/system/prefs")["theme"], "light")
    def test_theme_inject(self):
        p = self.root / "index.html"; p.write_bytes(b'<html lang="en"><body>mesh</body></html>'); sd.save_prefs("light", atomic_json)
        h = sd.render_index_with_theme(p); self.assertIn(b'data-theme="light"', h); self.assertIn(b'lang="en"', h)
    def test_persist(self):
        st = {"metrics": {"gpu": {"available": True, "gpus": [], "gpu": {"name": "test-gpu", "temperature_c": 32.0, "utilization_gpu_percent": 0.0, "fan_percent": 41.0, "power_w": 19.77, "vram_used_bytes": 1148*1024*1024, "vram_total_bytes": 32760*1024*1024, "vram_percent": 3.5}}, "cpu": sd.get_cpu_metrics(), "memory": {"available": True, "percent_used": 20.0, "used_bytes": 100, "total_bytes": 500}, "drives": [{"letter": "C", "available": True, "percent_used": 70.0, "free_bytes": 300, "total_bytes": 1000}, {"letter": "D", "available": True, "percent_used": 10.0, "free_bytes": 900, "total_bytes": 1000}]}, "llm": []}
        sd.persist_sample(st)
        db = sqlite3.connect(sd.DB_PATH)
        try:
            mr = db.execute("SELECT gpu_name, gpu_temp, cpu_temp FROM system_metrics").fetchall()
            lr = db.execute("SELECT json FROM system_llm_state").fetchall()
        finally: db.close()
        self.assertEqual(mr[0]["gpu_name"], "test-gpu"); self.assertIsNone(mr[0]["cpu_temp"]); self.assertEqual(json.loads(lr[0]["json"]), [])

if __name__ == "__main__":
    unittest.main()
'''

FILES[".gitignore"] = "data/\n__pycache__/\n*.pyc\n"

FILES["run.cmd"] = (
    "@echo off\r\n"
    "cd /d \"%~dp0\"\r\n"
    "python -m unittest test_system_dashboard.py\r\n"
    "if errorlevel 1 (\r\n"
    "  echo Tests failed. Not starting server.\r\n"
    "  exit /b 1\r\n"
    ")\r\n"
    "start \"\" http://127.0.0.1:8780/#system\r\n"
    "python server.py 8780\r\n"
)

FILES["README.md"] = (
    "# Mesh System Dashboard - standalone preview\n\n"
    "Phase 1 read-only monitor. Stdlib Python only. Vanilla HTML/CSS/JS.\n"
    "No psutil/pynvml/cryptography. No control buttons. Loopback bind + Host/Origin gate.\n\n"
    "Run on Echo's PC (reads the machine it runs on):\n\n"
    "    run.cmd\n"
    "    # or: python -m unittest test_system_dashboard.py && python server.py 8780\n\n"
    "Open: http://127.0.0.1:8780/#system\n\n"
    "Truthful: GPU live; CPU temp/fan/power 'unavailable'; RAM + C/D live;\n"
    "Strata 'unavailable' if 8094 down, 'loaded' only if /health says so. No guessed ids.\n\n"
    "To fold into the real Mesh PWA: copy system_dashboard.py + test_system_dashboard.py\n"
    "into D:/Dev/Onoes-Mesh-sandbox and apply the 3 small edits to server.py / index.html / app.js.\n"
    "This folder's module and frontend are the same source of truth.\n"
)

for name, content in FILES.items():
    (ROOT / name).write_text(content, encoding="utf-8", newline="\n")

print("Wrote preview folder to:", ROOT)
print("Next:")
print("  cd", ROOT)
print("  run.cmd        (or: python -m unittest test_system_dashboard.py && python server.py 8780)")
print("  open http://127.0.0.1:8780/#system")
