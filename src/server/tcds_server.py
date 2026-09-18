#!/usr/bin/env python3

import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


HOST = "0.0.0.0"
PORT = 8080
VERSION = "0.4.0"

TERMINALS = {}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class TCDSRequestHandler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()

        self.wfile.write(payload)

    def read_json(self):
        content_length = self.headers.get("Content-Length")

        if not content_length:
            return None

        try:
            length = int(content_length)
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))

        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def do_GET(self):
        if self.path == "/api/v1/status":
            self.send_json({
                "status": "ok",
                "service": "tcds-server",
                "version": VERSION
            })
            return

        if self.path == "/api/v1/terminals":
            self.send_json({
                "terminals": list(TERMINALS.values())
            })
            return

        self.send_json({
            "status": "error",
            "message": "Endpoint not found"
        }, 404)

    def do_POST(self):

        if self.path == "/api/v1/terminals/register":
            self.register_terminal()
            return

        if self.path == "/api/v1/terminals/heartbeat":
            self.heartbeat()
            return

        self.send_json({
            "status": "error",
            "message": "Endpoint not found"
        }, 404)

    def register_terminal(self):
        data = self.read_json()

        if not data:
            self.send_json({
                "status": "error",
                "message": "Invalid JSON"
            }, 400)
            return

        name = data.get("name")
        mac = data.get("mac")

        if not name or not mac:
            self.send_json({
                "status": "error",
                "message": "name and mac are required"
            }, 400)
            return

        terminal = {
            "name": name,
            "mac": mac.lower(),
            "hostname": data.get("hostname"),
            "ip": data.get("ip"),
            "last_seen": utc_now()
        }

        TERMINALS[name] = terminal

        logging.info(
            "Terminal enregistré : %s (%s)",
            name,
            mac
        )

        self.send_json({
            "status": "registered",
            "terminal_id": name
        }, 201)

    def heartbeat(self):
        data = self.read_json()

        if not data:
            self.send_json({
                "status": "error",
                "message": "Invalid JSON"
            }, 400)
            return

        name = data.get("name")
        mac = data.get("mac")

        if not name or not mac:
            self.send_json({
                "status": "error",
                "message": "name and mac are required"
            }, 400)
            return

        terminal = TERMINALS.get(name)

        if not terminal:
            self.send_json({
                "status": "error",
                "message": "Terminal not registered"
            }, 404)
            return

        if terminal["mac"] != mac.lower():
            self.send_json({
                "status": "error",
                "message": "MAC address mismatch"
            }, 403)
            return

        terminal["last_seen"] = utc_now()

        logging.info(
            "Heartbeat : %s (%s)",
            name,
            mac
        )

        self.send_json({
            "status": "ok",
            "terminal_id": name,
            "last_seen": terminal["last_seen"]
        })

    def log_message(self, format, *args):
        logging.info(
            "%s - %s",
            self.client_address[0],
            format % args
        )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logging.info("TCDS Server %s démarrage", VERSION)
    logging.info("Écoute sur %s:%s", HOST, PORT)

    server = HTTPServer((HOST, PORT), TCDSRequestHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Arrêt de TCDS Server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
