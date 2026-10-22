"""Hello-agent — the smallest "agent" for the first parts of the lesson (no LLM, no libraries).

It answers every GET with JSON: who it is and WHERE it runs (pod, node). That is all we
need to see Kubernetes at work: several pods, load balancing, restarts, rolling updates,
configuration from ConfigMap / Secret.

    GET /                              who am I: agent name, version, pod, node, config
    GET /.well-known/agent-card.json   a tiny "agent card" (as in A2A, lesson 3)
    GET /healthz                       for liveness / readiness probes
    GET /work                          "think hard": burn CPU for ~0.2 s (autoscaling demo, part 8)

    HEALTHY_SECONDS=30                 /healthz starts failing after 30 s (liveness demo, part 8)
"""

import hashlib
import json
import os
import signal
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CONFIG_FILE = Path("/etc/agent/config.yaml")       # mounted from a ConfigMap (part 4)
STARTED = time.time()
HEALTHY_SECONDS = float(os.getenv("HEALTHY_SECONDS", "0"))   # 0 = always healthy


def whoami() -> dict:
    return {
        "agent": os.getenv("AGENT_NAME", "hello-agent"),
        "version": os.getenv("AGENT_VERSION", "?"),
        "greeting": os.getenv("GREETING", "Привет! Я агент."),
        "pod": os.getenv("POD_NAME", socket.gethostname()),     # the pod name = the container hostname
        "node": os.getenv("NODE_NAME", "?"),                   # set by Kubernetes (downward API)
        "config_file": CONFIG_FILE.read_text() if CONFIG_FILE.exists() else None,
        "api_key_set": bool(os.getenv("API_KEY")),             # from a Secret; never print the key itself
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = 200
        if self.path == "/healthz":
            healthy = not HEALTHY_SECONDS or time.time() - STARTED < HEALTHY_SECONDS
            status, body = (200, {"status": "ok"}) if healthy else (500, {"status": "сломался"})
        elif self.path == "/work":
            deadline = time.time() + 0.2                       # pretend the agent thinks: burn CPU
            while time.time() < deadline:
                hashlib.sha256(b"agent").digest()
            body = {"pod": whoami()["pod"], "work": "done"}
        elif self.path == "/.well-known/agent-card.json":
            info = whoami()
            body = {"name": info["agent"], "version": info["version"], "description": info["greeting"]}
        else:
            body = whoami()
        data = json.dumps(body, ensure_ascii=False, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):                       # one short line per request
        print(f"{self.address_string()} {self.command} {self.path}", flush=True)


if __name__ == "__main__":
    # In a container our process is PID 1, which ignores SIGTERM by default: without this line
    # Kubernetes would wait 30 s and then kill the pod on every restart / rolling update.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"hello-agent v{os.getenv('AGENT_VERSION', '?')} listening on :8080", flush=True)
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
