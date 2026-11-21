"""Builds what the assistant is told about the user's project. Only files the user is allowed to read are used,
and everything is cut to the configured size so a request never exceeds the model's limit silently."""
import difflib

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import User, Workspace, WorkspaceFile
from app.services import workflow as W

SKIP_DIRS = ("node_modules/", ".git/", "dist/", "build/", "__pycache__/", ".venv/", "venv/", "target/", ".next/")
SKIP_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock")

BASE_PROMPT = """You are the WORKCODE AI coding assistant, built into the company's coding workspace. You help with \
writing, explaining, fixing, debugging, refactoring, optimising and testing code in any language \
(HTML, CSS, JavaScript, TypeScript, React, Angular, Vue, Node.js, Python, Java, Spring Boot, C#, .NET, Flutter, Dart, SQL, PHP and others).

Rules:
- Use the project context given below. Work with the user's real files, names and style; do not invent files you were not shown. \
If you need a file you cannot see, ask for it.
- When you create or change a file, output the COMPLETE new content of that file in ONE fenced code block whose first line is the \
language followed by path=<path relative to the project root>, for example:
```jsx path=src/App.jsx
...whole file...
```
One block per file. Never shorten such a block with "..." or "rest unchanged": the user previews a diff and applies the block as the whole file.
- For a snippet that is not a whole file, use a normal fenced block with the language and no path.
- Put shell commands in ```bash blocks, one command per line. You cannot run anything yourself; the user decides whether to run a command. \
Warn clearly before any command that deletes or overwrites data.
- Never claim that you ran code, installed something or saw output that was not given to you.
- Explain the cause of an error before the fix. Answer in the language the user writes in."""

# How the code itself must look. Kept apart from the output-format rules above so each can be changed alone.
STYLE_PROMPT = """Coding style: write code the way a careful, experienced developer writes it by hand, so that a beginner \
and the next developer can read, debug and change it.
- Simple, step-by-step logic. No clever one-liners, no nested ternaries, no long chained expressions. \
If a line needs a second reading, split it into named steps.
- Meaningful names for variables, functions, components and files (totalPrice, not tp; handleLoginSubmit, not fn1). \
Follow the normal conventions and formatting of the language, with consistent indentation and naming.
- Small functions that do one thing. No abstraction, pattern, wrapper, config layer or helper that the task does not need.
- Short, useful comments only where the reason or the logic is not obvious. Do not comment every line and do not repeat the code in words: \
a comment like "Function to add a todo" above handleAddTodo adds nothing, leave it out.
- Create only the files the project needs. Use a simple, professional folder structure that fits the size of the project: \
a small page does not need layers. For example a React app uses, only as far as needed, \
src/components, src/pages, src/services, src/hooks, src/styles, src/App.jsx, src/main.jsx. Reuse a component instead of copying markup.
- Real-world practice: handle errors and show meaningful error messages, validate user input, make the UI responsive, \
keep API addresses, keys and database settings in environment variables (add a .env.example with empty values, never a real secret), \
open and close database connections properly, never build SQL by joining strings with user input.
- No fake APIs, placeholder functions, "TODO: implement" bodies or made-up sample data unless the user asks for them. \
If something real is needed that you do not have (an API address, a key, a table layout), say so and ask, or leave one clearly named setting for it.

When you change an existing project:
- Read the files you were given first and understand what the code already does.
- Change only what the request needs and only the files that must change. Keep working code, behaviour, names and the existing style as they are. \
Do not reformat or rewrite parts that were not asked about.
- Give each changed file as a complete path= block (the user sees a diff and approves it before anything is saved), \
and say in one line per file what you changed and why.

How to explain (simple English, short sentences, no jargon without a few words of explanation):
- When you generate a new project (two or more new files), you MUST end the answer with all six of these short sections, \
with exactly these headings and in this order (never for a change to existing files): \
"What it does", "Why this approach", "How the main functions work", "How the files are connected", "How to run it" (commands in a bash block), "How to change it later".
- For a question: answer in plain words, show a small practical example, give the steps in order, \
name the exact file and place to change, and say how to run and test the change.
- For a change to existing files, a small fix or a quick question, do NOT use those sections. Keep it short: \
what was wrong or what is needed, the changed file, one line on what changed, how to test it. Do not pad the answer.
- Check every command and code example you give letter by letter: names must match the code exactly."""

ROLE_NOTE = {
    "intern": "The user is an intern who is learning. Explain step by step in simple words and say why, not only what.",
    "offroll": "The user is a developer working on an assigned task. Be practical and direct.",
    "onroll": "The user is a senior developer who also reviews other people's code. Be direct; point out risks and quality problems.",
    "admin": "The user is an administrator viewing a project read-only.",
}


def system_prompt(actor: User, extra: str | None) -> str:
    parts = [BASE_PROMPT, STYLE_PROMPT, ROLE_NOTE.get(actor.role, "")]
    if extra:
        parts.append("Company instructions:\n" + extra.strip())
    return "\n\n".join(p for p in parts if p)


def _fence(path: str, text: str) -> str:
    return f"```text path={path}\n{text}\n```" if "```" not in text else f"<file path=\"{path}\">\n{text}\n</file>"


class Budget:
    def __init__(self, limit: int):
        self.left, self.parts, self.meta = limit, [], []

    def add(self, kind: str, title: str, text: str, path: str | None = None, cap: int | None = None) -> bool:
        text = text or ""
        if not text.strip():
            return False
        room = min(self.left, cap or self.left)
        if room < 200:
            self.meta.append({"kind": kind, "path": path, "chars": 0, "truncated": True, "skipped": True})
            return False
        cut = len(text) > room
        body = text[:room] + ("\n[... cut: too long ...]" if cut else "")
        self.parts.append(f"### {title}\n{_fence(path, body) if path else body}")
        self.left -= len(body)
        self.meta.append({"kind": kind, "path": path, "chars": len(body), "truncated": cut})
        return True


def build(db: Session, actor: User, ws: Workspace | None, opts: dict, limit: int) -> tuple[str, list[dict]]:
    """opts: active_path, active_content, selection, files[], tree, project, terminal, run_output, attachments[]"""
    b = Budget(max(2000, limit))
    files: list[WorkspaceFile] = []
    if ws is not None:
        files = (db.query(WorkspaceFile).filter(WorkspaceFile.workspace_id == ws.id, WorkspaceFile.deleted_at.is_(None))
                 .order_by(WorkspaceFile.path).all())
    by_path = {f.path: f for f in files}
    active = (opts.get("active_path") or "").strip()

    if opts.get("selection"):
        b.add("selection", f"Selected code{f' (from {active})' if active else ''}", opts["selection"], cap=30000)
    if opts.get("terminal"):
        b.add("terminal", "Terminal output (most recent at the end)", opts["terminal"][-12000:])
    if opts.get("run_output"):
        b.add("run_output", "Output of the last Run / build", opts["run_output"][-12000:])
    for a in (opts.get("attachments") or [])[:5]:
        b.add("attachment", f"Attached file {a.get('name', 'file')}", a.get("content") or "", path=a.get("name") or "attachment", cap=40000)

    sent = set()
    if active and (opts.get("active_content") is not None or active in by_path):
        # the editor's current text wins over the last saved copy
        text = opts["active_content"] if opts.get("active_content") is not None else by_path[active].content
        if ws is None or active in by_path or opts.get("active_content") is not None:
            if b.add("file", f"Current open file: {active}", text or "", path=active):
                sent.add(active)
    for path in (opts.get("files") or [])[:30]:
        if path in by_path and path not in sent:
            if b.add("file", f"File: {path}", by_path[path].content or "", path=path):
                sent.add(path)
    if (opts.get("tree") or opts.get("project")) and files:
        listing = "\n".join(f"{f.path}  ({len(f.content or '')} chars)" for f in files)
        b.add("tree", "Project folder structure", listing, cap=8000)
    if opts.get("project"):
        for f in sorted(files, key=lambda f: len(f.content or "")):          # small files first: more of the project fits
            if f.path in sent or f.path.endswith(SKIP_FILES) or any(d in f.path + "/" for d in SKIP_DIRS):
                continue
            if "\x00" in (f.content or ""):
                continue
            if b.add("file", f"File: {f.path}", f.content or "", path=f.path):
                sent.add(f.path)
    return "\n\n".join(b.parts), b.meta


# ---- patch preview -----------------------------------------------------------------------
def preview_change(existing: str | None, path: str, content: str) -> dict:
    old = existing or ""
    status = "new" if existing is None else "unchanged" if old == content else "modified"
    plus, minus = W.line_stat(old, content)
    diff = "\n".join(difflib.unified_diff(old.splitlines(), content.splitlines(), f"current/{path}", f"proposed/{path}",
                                          lineterm="", n=3))
    return {"path": path, "status": status, "lines_added": plus, "lines_removed": minus, "diff": diff}


def check_size(content: str):
    if len(content.encode()) > settings.MAX_FILE_BYTES:
        raise HTTPException(413, "A proposed file is larger than the 1 MB limit")
