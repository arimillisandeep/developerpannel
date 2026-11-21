"""Really install, build and run the project templates on this machine (needs internet, node, python, java).
Usage: python scripts/verify_templates.py [template ids...]   Prints PASS / FAIL / SKIP per template."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.project_templates import BY_ID, TEMPLATES  # noqa: E402


def sh(cmd, cwd, timeout=300, env=None):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"`{cmd}` failed:\n{(r.stdout + r.stderr)[-800:]}")
    return r.stdout


def serve(cmd, cwd, url, expect, env=None, post=None):
    p = subprocess.Popen(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})},
                         start_new_session=True)
    try:
        last = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                body = urllib.request.urlopen(url, timeout=2).read().decode()
                assert expect in body, body[:200]
                if post:
                    req = urllib.request.Request(post[0], data=json.dumps(post[1]).encode(), headers={"Content-Type": "application/json"})
                    assert urllib.request.urlopen(req, timeout=2).status == 201
                return
            except AssertionError:
                raise
            except Exception as e:  # not up yet
                last = e
        raise RuntimeError(f"server did not answer on {url}: {last}")
    finally:
        try:
            os.killpg(p.pid, 9)
        except Exception:
            p.kill()


def venv(d, req="requirements.txt"):
    sh(f"{sys.executable} -m venv .venv && .venv/bin/pip install -q -r {req}", d, 600)
    return str(Path(d) / ".venv/bin")


CHECKS = {
    "html": lambda d: None if all((Path(d) / p).exists() for p in ("index.html", "css/style.css", "js/app.js")) else 1 / 0,
    "react": lambda d: (sh("npm install --no-audit --no-fund", d, 600), sh("npm run build", d), (Path(d) / "dist/index.html").read_text()),
    "vue": lambda d: (sh("npm install --no-audit --no-fund", d, 600), sh("npm run build", d), (Path(d) / "dist/index.html").read_text()),
    "node": lambda d: (None if "Hello from WORKCODE" in sh("node index.js", d) else 1 / 0, sh("npm test", d)),
    "express": lambda d: (sh("npm install --no-audit --no-fund", d, 600),
                          serve("node src/server.js", d, "http://127.0.0.1:3911/api/items", "First item", {"PORT": "3911"},
                                ("http://127.0.0.1:3911/api/items", {"name": "x"}))),
    "python": lambda d: (None if "Hello from WORKCODE" in sh(f"{sys.executable} main.py", d) else 1 / 0,
                         sh(f"{venv(d)}/python -m pytest -q", d)),
    "flask": lambda d: serve(f"{venv(d)}/python -c \"from app import app; app.run(port=3912)\"", d, "http://127.0.0.1:3912/api/items", "First item",
                             post=("http://127.0.0.1:3912/api/items", {"name": "x"})),
    "fastapi": lambda d: serve(f"{venv(d)}/uvicorn main:app --port 3913", d, "http://127.0.0.1:3913/api/items", "First item",
                               post=("http://127.0.0.1:3913/api/items", {"name": "x"})),
    "django": lambda d: (lambda b: (sh(f"{b}/python manage.py check", d),
                                    serve(f"{b}/python manage.py runserver 3914 --noreload", d, "http://127.0.0.1:3914/api/health", "ok")))(venv(d)),
    "java": lambda d: None if "Hello from WORKCODE" in sh("javac -d out src/*.java && java -cp out Main", d) else 1 / 0,
    "fullstack": lambda d: (sh("npm install --no-audit --no-fund", f"{d}/server", 600), sh("npm install --no-audit --no-fund", f"{d}/client", 600),
                            sh("npm run build", f"{d}/client"),
                            serve("node src/server.js", f"{d}/server", "http://127.0.0.1:3915/api/items", "First item", {"PORT": "3915"})),
}

failed = False
for t in (TEMPLATES if len(sys.argv) < 2 else [BY_ID[i] for i in sys.argv[1:]]):
    if t["id"] not in CHECKS:
        print(f"SKIP  {t['id']:<11} no toolchain here ({t['needs']})")
        continue
    d = tempfile.mkdtemp(prefix=f"tpl-{t['id']}-")
    try:
        for path, content in t["files"].items():
            f = Path(d) / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
        CHECKS[t["id"]](d)
        print(f"PASS  {t['id']}")
    except Exception as e:
        failed = True
        print(f"FAIL  {t['id']}: {str(e)[:600]}")
    finally:
        shutil.rmtree(d, ignore_errors=True)
sys.exit(1 if failed else 0)
