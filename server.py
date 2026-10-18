#!/usr/bin/env python3
"""GT Recipe Book server (Python 3.7+, standard library only).

Serves the app and keeps every recipe in data/recipes.json.
Run:   python3 server.py            (opens your browser)
       python3 server.py --local    (only this computer can connect)
       python3 server.py --port 9000 --no-browser
"""
import argparse, json, os, re, shutil, socket, sys, tempfile, threading, time, webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "recipes.json")
COLS = ("recipes", "ingredients")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
MAX_DOC = 1_000_000          # one recipe
MAX_REPLACE = 40_000_000     # a whole backup
BACKUP_EVERY = 600           # seconds between automatic backups
BACKUPS_KEPT = 30


def valid_doc(col, v):
    if not isinstance(v, dict) or not isinstance(v.get("name"), str) or not v["name"].strip():
        return False
    if col == "recipes":
        ings = v.get("ings")
        if not isinstance(ings, list):
            return False
        for x in ings:
            if not isinstance(x, dict) or x.get("t") not in ("i", "r") or not isinstance(x.get("id"), str):
                return False
        if "method" in v and not (isinstance(v["method"], list) and all(isinstance(s, str) for s in v["method"])):
            return False
    return True


def valid_all(d):
    if not isinstance(d, dict):
        return False
    for c in COLS:
        part = d.get(c)
        if not isinstance(part, dict):
            return False
        for k, v in part.items():
            if not ID_RE.match(k) or not valid_doc(c, v):
                return False
    return True


class Db:
    """The whole database lives in memory and is mirrored to one JSON file.
    If the file is edited by hand while the server runs, the change is picked up."""

    def __init__(self, path):
        self.path = path
        self.dir = os.path.dirname(path)
        self.backups = os.path.join(self.dir, "backups")
        self.lock = threading.RLock()
        self.rev = 1
        self.mtime = None
        self.data = {c: {} for c in COLS}
        if os.path.exists(path):
            self.data = self._read()          # raises on a broken file so we never overwrite it
            self.mtime = os.stat(path).st_mtime_ns

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or any(not isinstance(d.get(c, {}), dict) for c in COLS):
            raise ValueError("recipes.json must contain 'recipes' and 'ingredients' objects")
        return {c: d.get(c, {}) for c in COLS}

    def refresh(self):
        try:
            m = os.stat(self.path).st_mtime_ns
        except FileNotFoundError:
            return
        if m == self.mtime:
            return
        self.mtime = m
        try:
            self.data = self._read()
            self.rev += 1
        except Exception as e:                # half-saved hand edit: keep serving the last good copy
            print(f"  ! Could not read recipes.json ({e}). Keeping the last good copy in memory.")

    def _backup(self, force=False):
        if not os.path.exists(self.path):
            return
        os.makedirs(self.backups, exist_ok=True)
        files = sorted(f for f in os.listdir(self.backups) if f.endswith(".json"))
        if not force and files and time.time() - os.path.getmtime(os.path.join(self.backups, files[-1])) < BACKUP_EVERY:
            return
        name = datetime.now().strftime("recipes-%Y%m%d-%H%M%S.json")
        shutil.copy2(self.path, os.path.join(self.backups, name))
        files = sorted(f for f in os.listdir(self.backups) if f.endswith(".json"))
        for old in files[:-BACKUPS_KEPT]:
            os.remove(os.path.join(self.backups, old))

    def save(self, force_backup=False):
        os.makedirs(self.dir, exist_ok=True)
        self._backup(force_backup)
        doc = {"app": "gt-recipe-book", "version": 3,
               "savedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
               "recipes": self.data["recipes"], "ingredients": self.data["ingredients"]}
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)         # atomic: the file is never half-written
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self.mtime = os.stat(self.path).st_mtime_ns
        self.rev += 1


DB = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, limit):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > limit:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return None

    def _doc_target(self, path):
        parts = path.split("/")                # ['', 'api', 'doc', col, id]
        if len(parts) == 5 and parts[2] == "doc" and parts[3] in COLS and ID_RE.match(unquote(parts[4])):
            return parts[3], unquote(parts[4])
        return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/data":
            with DB.lock:
                DB.refresh()
                have = parse_qs(u.query).get("rev", [""])[0]
                if have == str(DB.rev):
                    return self._send(200, {"rev": DB.rev, "same": True})
                return self._send(200, {"rev": DB.rev, **DB.data})
        if u.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        if u.path.startswith("/data/backups") or u.path.endswith((".py", ".bat", ".sh")) or u.path.endswith(".tmp"):
            return self.send_error(404)
        return super().do_GET()

    def do_PUT(self):
        u = urlparse(self.path)
        t = self._doc_target(u.path)
        if not t:
            return self._send(404, {"error": "not found"})
        v = self._body(MAX_DOC)
        if v is None or not valid_doc(t[0], v):
            return self._send(400, {"error": "invalid recipe data"})
        with DB.lock:
            DB.refresh()
            DB.data[t[0]][t[1]] = v
            DB.save()
            return self._send(200, {"rev": DB.rev})

    def do_DELETE(self):
        t = self._doc_target(urlparse(self.path).path)
        if not t:
            return self._send(404, {"error": "not found"})
        with DB.lock:
            DB.refresh()
            if DB.data[t[0]].pop(t[1], None) is not None:
                DB.save()
            return self._send(200, {"rev": DB.rev})

    def do_POST(self):
        if urlparse(self.path).path != "/api/replace":
            return self._send(404, {"error": "not found"})
        d = self._body(MAX_REPLACE)
        if d is None or not valid_all(d):
            return self._send(400, {"error": "invalid backup"})
        with DB.lock:
            DB.refresh()
            DB.data = {c: d[c] for c in COLS}
            DB.save(force_backup=True)      # whole-file replace (import, migration): always keep the previous file
            return self._send(200, {"rev": DB.rev})


def lan_ip():
    for target in ("8.8.8.8", "10.255.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 1))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
    return None


def main():
    global DB
    ap = argparse.ArgumentParser(description="GT Recipe Book server")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--local", action="store_true", help="only accept connections from this computer")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        DB = Db(DATA_FILE)
    except Exception as e:
        sys.exit(f"Cannot start: data/recipes.json is not valid ({e}).\n"
                 f"Fix the file, or copy a recent one from data/backups/, then run again.")
    host = "127.0.0.1" if a.local else "0.0.0.0"
    httpd = None
    for port in range(a.port, a.port + 10):
        try:
            httpd = ThreadingHTTPServer((host, port), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit(f"Ports {a.port}-{a.port + 9} are all busy. Try: python3 server.py --port 9000")
    print("GT Recipe Book is running")
    print(f"  This computer:       http://localhost:{port}")
    if not a.local:
        ip = lan_ip()
        if ip:
            print(f"  Phone (same Wi-Fi):  http://{ip}:{port}")
        print("  Anyone on this network who opens that address can view and edit the recipes.")
        print("  (Use --local to allow only this computer.)")
    print(f"  Recipes file:        {DATA_FILE}")
    print("Press Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
