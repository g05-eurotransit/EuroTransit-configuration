#!/usr/bin/env python3
"""Guarded Kafka 3.9 Connect REST operations; see the AKS memory runbook.

Only loopback port forwards are accepted. Configurations come from rendered CRs,
never GET /config (which can contain resolved passwords). HTTP error bodies and
offset values are deliberately not printed. This tool does not change Kubernetes.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class MigrationError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MigrationError("REST redirects are not allowed")


def request(base, path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise MigrationError(f"REST {method} failed with HTTP {exc.code}; inspect the worker privately") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise MigrationError("REST transport or JSON response failed; inspect the port forward privately") from None


def stopped(base, path, wait=0):
    deadline = time.monotonic() + wait
    while True:
        status = request(base, path + "/status")
        if status.get("connector", {}).get("state") == "STOPPED" and not status.get("tasks"):
            return
        if time.monotonic() >= deadline:
            raise MigrationError("Connector must be STOPPED with no tasks")
        time.sleep(1)


def canonical(offsets):
    if not isinstance(offsets, list) or not offsets:
        raise MigrationError("Refusing empty or invalid offsets; investigate source initialization")
    keys = []
    for item in offsets:
        if not isinstance(item, dict) or not isinstance(item.get("partition"), dict) or not isinstance(item.get("offset"), dict):
            raise MigrationError("Offsets must contain partition and non-null offset objects")
        keys.append(json.dumps(item["partition"], sort_keys=True))
    if len(set(keys)) != len(keys):
        raise MigrationError("Duplicate offset partitions")
    return sorted((json.dumps(item, sort_keys=True, separators=(",", ":")) for item in offsets))


def read_snapshot(filename, connector):
    snapshot = json.loads(Path(filename).read_text())
    if snapshot.get("format") != 1 or snapshot.get("connector") != connector:
        raise MigrationError("Snapshot format or connector identity mismatch")
    canonical(snapshot.get("offsets"))
    return snapshot["offsets"]


def verify(base, path, offsets):
    actual = request(base, path + "/offsets")["offsets"]
    if canonical(actual) != canonical(offsets):
        raise MigrationError("Offset comparison failed; keep both workers stopped")


def registration(manifest, connector):
    try:
        import yaml
    except ImportError:
        raise MigrationError("create requires PyYAML") from None
    docs = list(yaml.safe_load_all(Path(manifest).read_text()))
    matches = [d for d in docs if d and d.get("kind") == "KafkaConnector" and d.get("metadata", {}).get("name") == connector]
    if len(matches) != 1:
        raise MigrationError("Manifest must contain exactly one matching KafkaConnector")
    spec = matches[0]["spec"]
    if spec.get("tasksMax") != 1:
        raise MigrationError("Expected tasksMax: 1")
    config = spec["config"].copy()
    for key, value in config.items():
        if any(word in key.lower() for word in ("password", "secret", "token")):
            if not isinstance(value, str) or not value.startswith("${env:") or not value.endswith("}"):
                raise MigrationError("Only environment references are allowed for credentials")
    config["connector.class"] = spec["class"]
    config["tasks.max"] = "1"
    config = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in config.items()}
    return {"name": connector, "config": config, "initial_state": "STOPPED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stop", "export", "create", "import", "verify", "resume"))
    parser.add_argument("--url", required=True, help="http://127.0.0.1:<port>")
    parser.add_argument("--connector", required=True)
    parser.add_argument("--file", help="Exclusive export output or existing import/verify snapshot")
    parser.add_argument("--manifest", help="Rendered connector manifest for create")
    parser.add_argument("--wait", type=int, default=120)
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.url)
    if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1") or not url.port or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
        raise MigrationError("Use a plain HTTP loopback port-forward URL with explicit port")
    if args.wait < 0:
        raise MigrationError("Wait must be nonnegative")
    base = args.url.rstrip("/")
    path = "/connectors/" + urllib.parse.quote(args.connector, safe="")
    if args.action in ("export", "import", "verify", "resume") and not args.file:
        raise MigrationError("This action requires --file")
    if args.action == "stop":
        request(base, path + "/stop", "PUT")
        stopped(base, path, args.wait)
    elif args.action == "create":
        if not args.manifest:
            raise MigrationError("create requires --manifest")
        body = registration(args.manifest, args.connector)
        # POST fails if the connector exists, protecting its previous state.
        request(base, "/connectors", "POST", body)
        stopped(base, path, args.wait)
    else:
        stopped(base, path)
        if args.action == "export":
            offsets = request(base, path + "/offsets")["offsets"]
            canonical(offsets)
            snapshot = {"format": 1, "connector": args.connector, "source": base,
                        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "offsets": offsets}
            fd = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(snapshot, stream, sort_keys=True, indent=2)
                stream.write("\n")
        else:
            offsets = read_snapshot(args.file, args.connector)
            if args.action == "import":
                request(base, path + "/offsets", "PATCH", {"offsets": offsets})
            verify(base, path, offsets)
            if args.action == "resume":
                request(base, path + "/resume", "PUT")
    print(f"{args.action}: {args.connector}: OK")


if __name__ == "__main__":
    try:
        main()
    except MigrationError as exc:
        print(f"Migration step failed: {exc}. Keep workers stopped.", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError):
        # Avoid raw exceptions, which could expose response data or credential paths.
        print("Migration step failed; workers must remain stopped. Check inputs and private worker status.", file=sys.stderr)
        sys.exit(1)
