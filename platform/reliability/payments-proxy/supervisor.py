"""Loopback-only lease API. The supervisor owns the toxic and its bounded expiry."""
import http.server
import json
import os
import signal
import subprocess
import threading
import time
import urllib.request

REAL_API = "http://127.0.0.1:8475"
LOCK = threading.Lock()
DEADLINE = None
MAX_LEASE = 175  # Leave reset + scheduler margin inside the 180-second fault bound.


def api(path, method="GET", data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(REAL_API + path, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response) if response.status != 204 else None


class LeaseHandler(http.server.BaseHTTPRequestHandler):
    def respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/health", "/lease"):
            return self.respond(404, {"error": "unknown endpoint"})
        try:
            api("/version")
            with LOCK:
                remaining = max(0, DEADLINE - time.monotonic()) if DEADLINE else 0
            self.respond(200, {"leaseRemainingSeconds": remaining, "maximumSeconds": MAX_LEASE})
        except Exception:
            self.respond(503, {"error": "proxy unavailable"})

    def do_POST(self):
        global DEADLINE
        if self.path != "/lease":
            return self.respond(404, {"error": "unknown endpoint"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("invalid body length")
            data = json.loads(self.rfile.read(length))
            seconds = data["seconds"]
            if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= MAX_LEASE:
                raise ValueError("seconds must be an integer from 1 to 175")
            with LOCK:
                if DEADLINE is not None:
                    return self.respond(409, {"error": "lease already active; renewal forbidden"})
                # Arm expiry BEFORE touching the proxy: ambiguous creation outcomes are bounded too.
                DEADLINE = time.monotonic() + seconds
                api("/proxies/payments/toxics", "POST", {
                    "name": "payments-latency", "type": "latency", "stream": "downstream",
                    "toxicity": 1.0, "attributes": {"latency": 4000, "jitter": 100}})
            self.respond(201, {"seconds": seconds, "latencyMs": 4000, "jitterMs": 100})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})
        except Exception:
            self.respond(503, {"error": "toxic creation uncertain; watchdog remains armed"})

    def do_DELETE(self):
        global DEADLINE
        if self.path != "/lease":
            return self.respond(404, {"error": "unknown endpoint"})
        try:
            with LOCK:
                api("/reset", "POST", {})
                DEADLINE = None
            self.respond(200, {"reset": True})
        except Exception:
            self.respond(503, {"error": "reset failed; watchdog remains armed"})


def main():
    global DEADLINE
    proxy = subprocess.Popen(["toxiproxy", "-host=127.0.0.1", "-port=8475",
                              "-config=/config/proxies.json"])
    def stop(*_):
        proxy.terminate()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for _ in range(50):
            if proxy.poll() is not None:
                raise RuntimeError("proxy exited during startup")
            try:
                api("/reset", "POST", {})
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError("proxy startup timeout")
        # Thread only serves HTTP; the main thread independently owns expiry and child lifetime.
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 8474), LeaseHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(json.dumps({"event": "neutral_proxy_started", "maximumLeaseSeconds": MAX_LEASE}))
        while proxy.poll() is None:
            with LOCK:
                if DEADLINE is not None and time.monotonic() >= DEADLINE:
                    # Failure exits supervisor AND child; restart uses neutral static configuration.
                    api("/reset", "POST", {})
                    DEADLINE = None
                    print(json.dumps({"event": "lease_expired_reset"}))
            time.sleep(.1)
        raise RuntimeError("proxy exited")
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proxy.kill()


if __name__ == "__main__":
    main()
