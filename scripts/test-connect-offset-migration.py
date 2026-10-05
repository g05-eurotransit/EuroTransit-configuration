#!/usr/bin/env python3
"""Local REST simulator for migration safeguards; never contacts Kubernetes."""
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


HELPER = Path(__file__).with_name("connect-offset-migration.py")
NAME = "inventory-outbox-connector"
OFFSETS = [{"partition": {"server": "inventory"}, "offset": {"lsn": 1234}}]


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.workers = {"source": {NAME: {"state": "RUNNING", "offsets": copy.deepcopy(OFFSETS)}}, "target": {}}
        self.calls = []
        self.bodies = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, code, body=None):
                self.send_response(code)
                self.end_headers()
                if body is not None:
                    self.wfile.write(json.dumps(body).encode())

            def handle_request(self):
                parts = self.path.strip("/").split("/")
                test.calls.append((self.command, self.path))
                name = parts[1] if len(parts) > 1 else None
                worker = test.workers[self.server.worker]
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length)) if length else None
                if self.command == "POST":
                    test.bodies.append(body)
                    if body["name"] in worker:
                        return self.respond(409, {"error": "PASSWORD_MUST_NEVER_APPEAR"})
                    worker[body["name"]] = {"state": body["initial_state"], "offsets": []}
                    return self.respond(201, {"name": body["name"]})
                if name not in worker:
                    return self.respond(404, {"error": "PASSWORD_MUST_NEVER_APPEAR"})
                item = worker[name]
                if "status_override" in item and parts[2] == "status":
                    return self.respond(200, item["status_override"])
                action = parts[2]
                if action == "status":
                    return self.respond(200, {"connector": {"state": item["state"]}, "tasks": item.get("tasks", [] if item["state"] == "STOPPED" else [{"id": 0, "state": "RUNNING"}])})
                if action in ("stop", "resume"):
                    item["state"] = "STOPPED" if action == "stop" else "RUNNING"
                    return self.respond(202)
                if self.command == "PATCH":
                    if item["state"] != "STOPPED":
                        return self.respond(400)
                    item["offsets"] = body["offsets"]
                    return self.respond(200, {"message": "updated"})
                return self.respond(200, {"offsets": item["offsets"]})

            do_GET = do_PUT = do_PATCH = do_POST = handle_request

        self.servers = {}
        for worker in self.workers:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.worker = worker
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers[worker] = server
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.file = self.folder / "before.json"
        self.manifest = self.folder / "manifest.yaml"
        self.manifest.write_text(f"""kind: KafkaConnector
metadata: {{name: {NAME}}}
spec:
  class: io.debezium.connector.postgresql.PostgresConnector
  tasksMax: 1
  config:
    database.password: ${{env:INVENTORY_DB_PASSWORD}}
    topic.prefix: inventory
    slot.name: inventory_outbox
    transforms.outbox.table.expand.json.payload: true
""")

    def tearDown(self):
        for server in self.servers.values():
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def run_step(self, action, worker="source", file=None, ok=True, connector=NAME):
        server = self.servers[worker]
        cmd = [sys.executable, str(HELPER), action, "--url", f"http://127.0.0.1:{server.server_port}", "--connector", connector, "--wait", "0"]
        if action in ("export", "import", "verify", "resume"):
            cmd += ["--file", str(file or self.file)]
        if action == "create":
            cmd += ["--manifest", str(self.manifest)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        self.assertNotIn("PASSWORD_MUST_NEVER_APPEAR", result.stdout + result.stderr)
        return result

    def stopped_export(self):
        self.run_step("stop")
        self.run_step("export")

    def test_stopped_transfer_and_fresh_rollback(self):
        self.stopped_export()
        self.assertEqual(os.stat(self.file).st_mode & 0o777, 0o600)
        self.run_step("create", "target")
        body = self.bodies[-1]
        self.assertEqual(body["initial_state"], "STOPPED")
        self.assertEqual(body["config"]["database.password"], "${env:INVENTORY_DB_PASSWORD}")
        self.assertEqual(body["config"]["tasks.max"], "1")
        self.assertEqual(body["config"]["transforms.outbox.table.expand.json.payload"], "true")
        self.run_step("import", "target")
        self.run_step("verify", "target")
        self.run_step("resume", "target")
        # Simulate processed events, then rollback with current rather than old offsets.
        self.workers["target"][NAME]["offsets"][0]["offset"]["lsn"] = 5678
        self.run_step("stop", "target")
        self.run_step("verify", "target", ok=False)
        fresh = self.folder / "rollback-current.json"
        self.run_step("export", "target", file=fresh)
        self.run_step("import", "source", file=fresh)
        self.run_step("resume", "source", file=fresh)
        self.assertEqual(self.workers["source"][NAME]["offsets"][0]["offset"]["lsn"], 5678)
        self.assertFalse(any(path.endswith("/config") for _, path in self.calls))

    def test_guards_running_tasks_empty_and_wrong_identity(self):
        self.run_step("export", ok=False)
        self.stopped_export()
        self.run_step("export", ok=False)  # Export does not overwrite evidence.
        self.run_step("create", "target")
        self.run_step("create", "target", ok=False)
        self.run_step("resume", "target", ok=False)  # No imported offsets.
        self.workers["target"][NAME]["tasks"] = [{"id": 0, "state": "RUNNING"}]
        before = len(self.calls)
        self.run_step("import", "target", ok=False)
        self.assertFalse(any(method == "PATCH" for method, _ in self.calls[before:]))
        self.workers["target"][NAME]["tasks"] = []
        snapshot = json.loads(self.file.read_text())
        snapshot["connector"] = "payments-outbox-connector"
        self.file.write_text(json.dumps(snapshot))
        self.run_step("import", "target", ok=False)
        snapshot["connector"] = NAME
        snapshot["offsets"] = []
        self.file.write_text(json.dumps(snapshot))
        self.run_step("import", "target", ok=False)
        self.run_step("stop", connector="missing", ok=False)

    def test_missing_tasks_and_empty_offset_objects_are_rejected(self):
        self.stopped_export()
        self.run_step("create", "target")
        target = self.workers["target"][NAME]
        for status in [None, {}, {"connector": {"state": "STOPPED"}},
                       {"connector": {"state": "STOPPED"}, "tasks": None}]:
            target["status_override"] = status
            before = len(self.calls)
            self.run_step("import", "target", ok=False)
            self.assertFalse(any(method == "PATCH" for method, _ in self.calls[before:]))
        del target["status_override"]
        for partition, offset in [({}, {"lsn": 1234}), ({"server": "inventory"}, {})]:
            snapshot = json.loads(self.file.read_text())
            snapshot["offsets"] = [{"partition": partition, "offset": offset}]
            self.file.write_text(json.dumps(snapshot))
            before = len(self.calls)
            self.run_step("import", "target", ok=False)
            self.assertFalse(any(method == "PATCH" for method, _ in self.calls[before:]))

    def test_malformed_yaml_is_redacted(self):
        self.manifest.write_text("kind: KafkaConnector\nspec:\n  config:\n    database.password: [DO_NOT_LOG_THIS_PASSWORD\n")
        result = self.run_step("create", "target", ok=False)
        self.assertNotIn("DO_NOT_LOG_THIS_PASSWORD", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.calls, [])

    def test_literal_credentials_rejected_before_post(self):
        self.manifest.write_text(self.manifest.read_text().replace("${env:INVENTORY_DB_PASSWORD}", "DO_NOT_LOG_THIS_PASSWORD"))
        result = self.run_step("create", "target", ok=False)
        self.assertNotIn("DO_NOT_LOG_THIS_PASSWORD", result.stdout + result.stderr)
        self.assertEqual(self.calls, [])
        self.manifest.write_text(self.manifest.read_text().replace("DO_NOT_LOG_THIS_PASSWORD", "${env:INVENTORY_DB_PASSWORD}DO_NOT_LOG_THIS_PASSWORD${env:OTHER}"))
        result = self.run_step("create", "target", ok=False)
        self.assertNotIn("DO_NOT_LOG_THIS_PASSWORD", result.stdout + result.stderr)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
