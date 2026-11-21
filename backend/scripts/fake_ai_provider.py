"""A tiny OpenAI-compatible server for testing WORKCODE's AI plumbing WITHOUT a real key.

It is NOT an AI and is never used by the product. It only proves that the request really leaves the backend
with the stored key and the project context, and that streaming comes back. Its answer is derived from the
request (it rewrites the first <h1> it is shown), so the test fails if the context is not really sent.

    python scripts/fake_ai_provider.py 9911
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "sk-fake-live-check-key"
SEEN = []          # what the backend sent, read back by the check script through /_seen


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self._json(401, {"error": {"message": "Incorrect API key provided"}})
            return False
        return True

    def do_GET(self):
        if self.path == "/_seen":
            return self._json(200, SEEN)
        if self.path.endswith("/models"):
            if self._auth():
                self._json(200, {"data": [{"id": "fake-coder-1"}, {"id": "fake-coder-mini"}]})
            return
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self._auth():
            return
        msgs = body.get("messages", [])
        text = "\n".join(m.get("content", "") for m in msgs)
        SEEN.append({"model": body.get("model"), "stream": body.get("stream"), "roles": [m["role"] for m in msgs], "text": text})
        last = msgs[-1]["content"] if msgs else ""
        if "RATE" in last:
            return self._json(429, {"error": {"message": "Rate limit reached"}})
        if "TOOLONG" in last:
            return self._json(400, {"error": {"code": "context_length_exceeded", "message": "maximum context length"}})
        m = re.search(r"<h1>(.*?)</h1>", text)
        if "SLOW" in last:
            parts = [f"word{i} " for i in range(200)]
        elif m:
            parts = ["The heading says ", f"“{m.group(1)}”. ", "Here is the changed file:\n\n", "```html path=index.html\n", "<h1>Hello from AI</h1>\n", "```\n",
                     "\nand a new stylesheet:\n\n```css path=css/site.css\nh1 { color: teal; }\n```\n", "\nThen run:\n\n```bash\nnpm test\n```\n"]
        else:
            parts = ["No <h1> ", "was sent to me."]
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        try:
            for p in parts:
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n".encode()); self.wfile.flush()
                time.sleep(0.05 if "SLOW" in last else 0.01)
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 123, 'completion_tokens': 45}})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            SEEN.append({"closed_early": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9911), H).serve_forever()
