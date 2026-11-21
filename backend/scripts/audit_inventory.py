"""API audit step 1: list every backend route and every frontend API call, and match them.

    python scripts/audit_inventory.py            -> writes ../audit/routes.json, ../audit/frontend_calls.json
Reads code only; touches no database.
"""
import inspect, json, os, re, sys
os.environ.setdefault("JWT_SECRET", "audit-secret-not-for-production-000000001")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/audit_inventory.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.routing import APIRoute, APIWebSocketRoute
from app.main import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.join(os.path.dirname(ROOT), "frontend", "src")

def deps_of(dependant, seen=None):
    seen = seen if seen is not None else []
    for d in dependant.dependencies:
        if d.call is not None:
            name = getattr(d.call, "__name__", type(d.call).__name__)
            extra = ""
            if getattr(d.call, "__closure__", None):       # require_roles(...) style closures
                vals = [c.cell_contents for c in d.call.__closure__ if isinstance(c.cell_contents, (tuple, list, set, frozenset, str))]
                extra = "(" + ",".join(sorted(str(getattr(x, "value", x)) for v in vals for x in (v if not isinstance(v, str) else [v]))) + ")" if vals else ""
            seen.append(name + extra)
        deps_of(d, seen)
    return seen

from starlette.routing import compile_path

def flat(routes, prefix=""):
    """Newer FastAPI keeps included routers as one nested entry; walk into them."""
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            ctx = r.include_context
            yield from flat(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        else:
            yield prefix, r

routes = []
for prefix, r in flat(app.routes):
    if prefix and hasattr(r, "path"):
        full = prefix + r.path
        class V:      # a light view with the full path
            pass
        v = V(); v.__dict__.update({k: getattr(r, k, None) for k in ("endpoint", "methods", "dependant", "status_code")})
        v.path = full; v.path_regex = compile_path(full)[0]; v.__class__ = type("APIRouteView", (APIRoute,), {"__init__": lambda self: None}) if isinstance(r, APIRoute) else V
        r = v
    if isinstance(r, APIRoute):
        src = inspect.getsourcefile(r.endpoint); line = inspect.getsourcelines(r.endpoint)[1]
        body = [p.name + ":" + getattr(getattr(p, "field_info", None) and p.field_info.annotation, "__name__", "body") for p in r.dependant.body_params]
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            routes.append({"method": m, "path": r.path, "file": os.path.relpath(src, ROOT) + ":" + str(line), "func": r.endpoint.__name__,
                           "deps": sorted(set(deps_of(r.dependant))), "path_params": [p.name for p in r.dependant.path_params],
                           "query": [p.name for p in r.dependant.query_params], "body": body, "status": r.status_code or 200,
                           "regex": r.path_regex.pattern})
    elif isinstance(r, APIWebSocketRoute):
        src = inspect.getsourcefile(r.endpoint)
        routes.append({"method": "WS", "path": r.path, "file": os.path.relpath(src, ROOT), "func": r.endpoint.__name__, "deps": [], "path_params": [], "query": [], "body": [], "status": 101, "regex": r.path_regex.pattern})
    else:
        routes.append({"method": "MOUNT", "path": getattr(r, "path", str(r)), "file": "", "func": type(r).__name__, "deps": [], "path_params": [], "query": [], "body": [], "status": 0, "regex": ""})

# ---- frontend calls ----
calls = []
pat = re.compile(r"\bapi\.(get|post|put|patch|delete)\(\s*(`[^`]*`|'[^']*'|\"[^\"]*\")")
extra = re.compile(r"(?:streamChat|rawRequest)\(\s*(`[^`]*`|'[^']*')")
for d, _, fs in os.walk(FRONT):
    if os.sep + "tests" in d: continue
    for f in fs:
        if not f.endswith((".js", ".jsx")): continue
        p = os.path.join(d, f); text = open(p).read()
        for m in pat.finditer(text):
            calls.append({"method": m.group(1).upper(), "url": m.group(2)[1:-1], "file": os.path.relpath(p, os.path.dirname(FRONT)) + ":" + str(text[:m.start()].count("\n") + 1)})
        for m in extra.finditer(text):
            calls.append({"method": "POST", "url": m.group(1)[1:-1], "file": os.path.relpath(p, os.path.dirname(FRONT)) + ":" + str(text[:m.start()].count("\n") + 1)})
        for m in re.finditer(r"api\.(get|post|put|patch|delete)\(\s*([A-Za-z_][\w.]*)", text):
            calls.append({"method": m.group(1).upper(), "url": "<variable " + m.group(2) + ">", "file": os.path.relpath(p, os.path.dirname(FRONT)) + ":" + str(text[:m.start()].count("\n") + 1)})

def sample(url):
    u = re.sub(r"\$\{[^}]*\}", "1", url).split("?")[0]
    return "/api" + u if not u.startswith("/api") else u

for c in calls:
    if c["url"].startswith("<variable"): c["match"] = None; continue
    s = sample(c["url"])
    hits = [r for r in routes if r["method"] == c["method"] and r["regex"] and re.match(r["regex"], s)]
    anym = [r for r in routes if r["regex"] and re.match(r["regex"], s)]
    c["match"] = (hits[0]["method"] + " " + hits[0]["path"]) if hits else None
    c["other_methods"] = sorted({r["method"] for r in anym}) if not hits else []
used = {c["match"] for c in calls if c.get("match")}
for r in routes: r["frontend"] = sorted({c["file"] for c in calls if c.get("match") == r["method"] + " " + r["path"]})
out = os.path.join(os.path.dirname(ROOT), "audit")
json.dump(routes, open(os.path.join(out, "routes.json"), "w"), indent=1)
json.dump(calls, open(os.path.join(out, "frontend_calls.json"), "w"), indent=1)
api = [r for r in routes if r["method"] not in ("MOUNT",)]
print("backend routes:", len(api), "| frontend call sites:", len(calls), "| distinct matched:", len(used))
print("\nFRONTEND CALLS WITH NO BACKEND ROUTE:")
for c in calls:
    if not c.get("match"): print("  ", c["method"], c["url"], c["file"], "other methods:", c.get("other_methods"))
print("\nBACKEND ROUTES WITH NO FRONTEND CALL:")
for r in api:
    if not r["frontend"]: print("  ", r["method"], r["path"], r["file"])
dup = {}
for r in api: dup.setdefault((r["method"], r["path"]), []).append(r["file"])
print("\nDUPLICATES:", {k: v for k, v in dup.items() if len(v) > 1})
print("\nNO AUTH DEPENDENCY:")
for r in api:
    if not any("user" in d.lower() or "role" in d.lower() or "require" in d.lower() for d in r["deps"]): print("  ", r["method"], r["path"], r["deps"])
