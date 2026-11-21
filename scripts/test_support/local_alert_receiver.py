"""Bounded webhook capture for the isolated incident project only."""

import json
import re
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

messages = deque(maxlen=256)
label_names = {"alertname", "scope", "role", "worker_slot", "consumer", "source"}
label_value = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}")
identifier = re.compile(r"[0-9a-f]{16}")


def labels(values):
    return {
        key: value
        for key, value in values.items()
        if key in label_names and label_value.fullmatch(value)
    }


def timestamp(value):
    return datetime.fromisoformat(value).isoformat()


def payload(document):
    status = document["status"]
    if status not in {"firing", "resolved"} or not 1 <= len(document["alerts"]) <= 64:
        raise ValueError("Unexpected notification shape")
    alerts = []
    for alert in document["alerts"]:
        identity = labels(alert["labels"])
        if (
            identity.get("scope") != "restaurantos-local"
            or alert["status"] not in {"firing", "resolved"}
            or not identifier.fullmatch(alert["fingerprint"])
        ):
            raise ValueError("Unexpected notification identity")
        alerts.append(
            {
                "status": alert["status"],
                "labels": identity,
                "fingerprint": alert["fingerprint"],
                "startsAt": timestamp(alert["startsAt"]),
                "endsAt": timestamp(alert["endsAt"]),
            }
        )
    return {
        "status": status,
        "groupLabels": labels(document["groupLabels"]),
        "alerts": alerts,
        "receivedAt": datetime.now(UTC).isoformat(),
    }


class Receiver(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/alerts" or not 0 < size <= 65536:
                raise ValueError("Unexpected request")
            messages.append(payload(json.loads(self.rfile.read(size))))
        except (KeyError, ValueError, AttributeError, TypeError, OSError):
            self.send_error(400)
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        body = json.dumps(list(messages)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    with HTTPServer(("0.0.0.0", 8080), Receiver) as server:
        server.serve_forever()
