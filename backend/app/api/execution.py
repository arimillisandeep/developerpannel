from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.languages import BY_ID, LANGUAGES, for_path
from app.core.security import RateLimiter
from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import RunIn
from app.services import runner
from app.services.common import activity, audit, commit
from app.api.workspaces import _file, live_files, owned_workspace

router = APIRouter(prefix="/api", tags=["execution"])
run_limiter = RateLimiter(20, 60)   # 20 runs per minute per user


def lang_dict(l: dict, available: bool) -> dict:
    d = {k: l[k] for k in ("id", "name", "extensions", "monaco", "kind", "file", "template", "note")}
    if l["kind"] == "run":
        d["image"] = l["image"]
        d["image_state"] = runner.image_state(l["image"]) if available else "unknown"
    return d


@router.get("/languages")
def languages(actor: User = Depends(get_current_user)):
    st = runner.status()
    return {"runner": st, "languages": [lang_dict(l, st["available"]) for l in LANGUAGES]}


@router.post("/languages/{lang_id}/pull", status_code=202)
def pull_image(lang_id: str, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Admin: download the Docker image for one language (runs in the background)."""
    if actor.role != P.ADMIN:
        raise HTTPException(403, "Only admins can install language images")
    l = BY_ID.get(lang_id)
    if not l or l["kind"] != "run":
        raise HTTPException(404, "This language has no runner image")
    st = runner.status(force=True)
    if not st["available"]:
        raise HTTPException(503, st["reason"])
    runner.pull(l["image"])
    audit(db, actor, "runner.pull_image", "languages", None, new={"language": lang_id, "image": l["image"]}, ip=client_ip(request))
    commit(db)
    return {"image": l["image"], "image_state": "pulling"}


@router.post("/workspaces/{ws_id}/run")
def run_file(ws_id: int, body: RunIn, request: Request, actor: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    """Run one file of your own workspace in an isolated container. Uses the files saved on the server."""
    ws, task = owned_workspace(db, actor, ws_id, for_write=False)
    # A reader of the workspace may run what is in it - that is what a review is for. It changes nothing: the
    # files are the saved ones, the container is throw-away, and the run is bookmarked as a reviewer's run.
    # Writing stays the owner's alone (for_write above).
    as_reviewer = ws.user_id != actor.id
    f = _file(db, ws_id, body.file_id)
    lang = for_path(f.path)
    if not lang:
        raise HTTPException(422, "Unknown file type. Give the file an extension such as .py, .js or .java.")
    if lang["kind"] != "run":
        raise HTTPException(422, lang["note"] or ("Use the HTML preview tab for this file." if lang["kind"] == "preview"
                                                  else f"{lang['name']} files cannot be run."))
    if not run_limiter.allow(str(actor.id)):
        raise HTTPException(429, "Too many runs. Wait a minute.")
    files = [(x.path, x.content) for x in live_files(db, ws_id)]
    db.commit()   # release the DB connection's transaction while the program runs
    try:
        result = runner.run(actor.id, lang, files, f.path, body.stdin)
    except runner.RunnerUnavailable as e:
        raise HTTPException(503, str(e))
    activity(db, actor.id, "code.run", {"workspace_id": ws_id, "file": f.path, "language": lang["id"],
                                        "as_reviewer": as_reviewer,
                                        "status": result["status"], "exit_code": result["exit_code"],
                                        "duration_ms": result["duration_ms"]}, ip=client_ip(request))
    commit(db)
    return result


@router.post("/workspaces/{ws_id}/run/stop")
def stop_run(ws_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_workspace(db, actor, ws_id, for_write=False)
    return {"stopped": runner.stop(actor.id)}
