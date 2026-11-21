# WORKCODE AI Coding Assistant (build 17)

A chat panel on the right side of the coding workspace. It talks to a real AI service through the WORKCODE
backend. There is no built-in "pretend" AI: until an administrator adds a provider and key, the panel says
"not set up" and answers nothing.

## 1. Setup (Admin, once)

1. Set a long random `AI_KEY_SECRET` in `backend/.env` (used to encrypt stored API keys; if empty, `JWT_SECRET` is used).
   Do not change it later, or stored keys must be typed in again.
2. `pip install -r requirements.txt` (adds `cryptography`) and `alembic upgrade head` (migration `0005`).
3. Log in as Admin → **AI assistant** in the menu → **Add AI provider**:
   choose the service (OpenAI, OpenRouter, Groq, Gemini's OpenAI-compatible address, a local Ollama, or any
   other OpenAI-compatible address), paste the API key, press **Save and test connection**, tick the models
   users may choose, **Save**.
4. On the same page: switch AI on/off per role, set messages per day per role, the context size limit,
   the answer length limit and optional company instructions. The usage table shows numbers per person.

The server must be able to reach the provider's address (firewall / proxy).

## 2. Using it (all roles)

Open a task in the coding workspace → **✦ AI** in the top bar (or `Ctrl+I`, or the command palette).
Drag the left edge of the panel to resize; ✕ closes it. Open/closed and width are remembered.

- **Context** button: choose what is sent with the question — open file (the text in the editor, even if
  unsaved), selected code, other files, folder structure, entire project, terminal output, run/build/preview
  errors. 📎 attaches a text file from your PC. Each answer lists what was actually sent.
- Quick buttons: Explain selected code, Fix selected code, Review current file, Analyze project,
  Fix terminal error, Generate tests.
- On every code block: Copy, Insert at cursor, Replace selection, Insert below, Create new file.
  Inserts go through the editor, so `Ctrl+Z` undoes them and autosave stores them.
- When the answer contains whole files (a code block with `path=...`): **Preview changes** shows a diff per
  file (green added, red removed). Tick the files you accept, **Apply**. Unticked files are not touched.
  Nothing is ever written before you press Apply. Every applied file gets a saved version marked "ai", so
  the old text can be restored from the file's version history.
- Shell commands in an answer: **Send to terminal** only places the command in the terminal's input line.
  You press Enter yourself. Commands that delete or overwrite (rm -rf, git reset --hard, DROP TABLE, sudo,
  pipe-to-shell …) need an extra confirmation first.
- ■ Stop, ↻ Regenerate, ☆ Save answer, ☰ history (search, rename, delete, saved answers), ＋ New chat, Clear.

## 3. Rules the server enforces

| Rule | How |
|---|---|
| API keys stay on the server | Encrypted in the database; no endpoint returns them; the browser only gets `key_set: true/false` |
| Private chats | Every conversation query is filtered by owner. Admins cannot read other people's chats; the usage page has numbers only |
| Project access | The assistant reads only projects the user may already open. Others get 403/404 and nothing is sent to the provider |
| Writing files | Only the project's owner, only while the task is editable (not while in review / completed) |
| Limits | Per-role on/off, messages per day per role, 15 questions per minute per user, context size cap |
| Errors | Wrong key, rate limit, too much text, timeout and "cannot reach provider" are shown as plain messages |

Text you send as context goes to the AI provider you configured. Choose a provider your company accepts
for source code.

## 4. API (all need login)

`GET /api/ai/status` · conversations: `GET|POST /api/ai/conversations`, `GET|PATCH|DELETE /api/ai/conversations/{id}`,
`POST …/{id}/clear`, `POST …/{id}/messages` (streamed, server-sent events), `POST …/{id}/regenerate` ·
`PATCH /api/ai/messages/{id}` (save), `POST /api/ai/messages/{id}/stop`, `GET /api/ai/saved` ·
`POST /api/ai/patch/preview`, `POST /api/ai/patch/apply` ·
Admin only: `/api/ai/providers` (+ `/{id}/test`), `/api/ai/settings`, `/api/ai/usage`.

Code: `backend/app/api/ai.py`, `app/services/ai_provider.py`, `app/services/ai_context.py`;
`frontend/src/pages/workspace/AIPanel.jsx`, `src/services/ai.js`, `src/components/Markdown.jsx`, `src/pages/admin/AISettings.jsx`.

## 5. Tests

- `backend/tests/test_ai.py` (10 tests, provider replaced by a mock transport).
- `frontend/src/tests/app.test.jsx` "AI assistant" (9 tests) and `src/tests/ai.test.js` (3 tests).
- `backend/scripts/live_ai_check.py`: 54 checks over real HTTP against a running server, with
  `scripts/fake_ai_provider.py` standing in for OpenAI. The fake server is a test tool only; the product never uses it.

## 6. Not done / not verified

- No real provider key was available while building, so answers from a real model (OpenAI etc.) were never seen.
  The OpenAI-compatible request/stream format is what was tested.
- The panel was never looked at in a real browser by the builder (no browser in the build sandbox); it is covered by component tests.
- Only OpenAI-compatible APIs. Anthropic's native API is not supported directly (use it through OpenRouter or a compatible gateway).
- The assistant does not run commands or create files by itself (by design). Running `npm install` etc. still needs the
  Docker-based terminal, and package installs / React dev-server preview (IDE Phase B) are still not built.
- No image attachments, no inline "ghost text" autocomplete, no cost in money (tokens only).
- Token counts are estimates when the provider does not report usage.

## 7. Code style rules (build 18)

Every question is sent with a fixed set of style rules (`STYLE_PROMPT` in `backend/app/services/ai_context.py`):
simple step-by-step code, meaningful names, small functions, comments only where needed, only the files and folders
the project needs, error handling, input validation, responsive UI, environment variables (`.env.example`), no fake
APIs or dummy data unless asked; when changing a project: read first, change only what is needed, keep the existing
style, show complete files so the diff preview works; new projects end with six sections (What it does, Why this
approach, How the main functions work, How the files are connected, How to run it, How to change it later);
small fixes get a short answer.

These are instructions to the model, not a guarantee. A model can ignore part of them, and smaller models do so more
often. The diff preview and the reviewer stay the real check. Admins can add company rules on the AI assistant page
("Company instructions").
