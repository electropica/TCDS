#!/usr/bin/env python3

import json
import logging
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

NETWORK_MODULE = PROJECT_ROOT / "src" / "network"
IDENTITY_MODULE = PROJECT_ROOT / "src" / "identity"

if str(NETWORK_MODULE) not in sys.path:
    sys.path.insert(0, str(NETWORK_MODULE))

if str(IDENTITY_MODULE) not in sys.path:
    sys.path.insert(0, str(IDENTITY_MODULE))

import tcds_network
import tcds_identity


SERVER_URL = "http://127.0.0.1:8080"
REGISTER_ENDPOINT = "/api/v1/terminals/register"
HEARTBEAT_ENDPOINT = "/api/v1/terminals/heartbeat"

VERSION = "0.1.0"
HEARTBEAT_INTERVAL = 30


def get_local_ip():
    status = tcds_network.get_network_status()

    for interface in status["active_interfaces"]:
        for address in interface["addresses"]:
            if "." in address:
                return address.split("/")[0]

    return None


def send_request(endpoint, data):
    url = SERVER_URL + endpoint

    payload = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)

    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8")
            return error.code, json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return error.code, None

    except urllib.error.URLError as error:
        logging.error("Serveur TCDS inaccessible : %s", error)
        return None, None


def build_terminal_info(identity):
    return {
        "name": identity["name"],
        "mac": identity["mac"],
        "hostname": socket.gethostname(),
        "ip": get_local_ip()
    }


def register(identity):
    data = build_terminal_info(identity)

    logging.info("Enregistrement du terminal : %s", identity["name"])

    status, response = send_request(
        REGISTER_ENDPOINT,
        data
    )

    if status == 201:
        logging.info(
            "Terminal enregistré : %s",
            response["terminal_id"]
        )
        return True

    logging.error(
        "Échec de l'enregistrement : HTTP %s",
        status
    )

    return False


def heartbeat(identity):
    data = {
        "name": identity["name"],
        "mac": identity["mac"]
    }

    status, response = send_request(
        HEARTBEAT_ENDPOINT,
        data
    )

    if status == 200:
        logging.info(
            "Heartbeat OK : %s",
            response["last_seen"]
        )
        return True

    logging.error(
        "Heartbeat échoué : HTTP %s",
        status
    )

    return False


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger = logging.getLogger("tcds-client")

    logger.info("TCDS Client %s démarrage", VERSION)

    identity = tcds_identity.get_identity()

    if not identity:
        logger.error("Identité du terminal indisponible")
        return 1

    logger.info("Terminal : %s", identity["name"])
    logger.info("MAC : %s", identity["mac"])

    if not register(identity):
        logger.error("Impossible d'enregistrer le terminal")
        return 1

    logger.info("Client TCDS actif")

    try:
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            heartbeat(identity)

    except KeyboardInterrupt:
        logger.info("Arrêt de TCDS Client")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
