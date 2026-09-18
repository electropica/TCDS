#!/usr/bin/env python3

import configparser
import json
import logging
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]

NETWORK_PATH = PROJECT_ROOT / "src" / "network"
IDENTITY_PATH = PROJECT_ROOT / "src" / "identity"

sys.path.insert(0, str(NETWORK_PATH))
sys.path.insert(0, str(IDENTITY_PATH))

import tcds_network
import tcds_identity


CONFIG_FILE = Path("/etc/tcds/tcds.conf")

REGISTER_ENDPOINT = "/api/v1/terminals/register"
HEARTBEAT_ENDPOINT = "/api/v1/terminals/heartbeat"

VERSION = "0.0.2"
HEARTBEAT_INTERVAL = 30


def load_config():
    config = configparser.ConfigParser()

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Fichier de configuration introuvable : {CONFIG_FILE}"
        )

    config.read(CONFIG_FILE)

    if not config.has_section("server"):
        raise ValueError("Section [server] absente de la configuration")

    host = config.get("server", "host", fallback="127.0.0.1")
    port = config.getint("server", "port", fallback=8080)

    return host, port


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )


def get_local_ip():
    status = tcds_network.get_network_status()

    for interface in status["active_interfaces"]:
        for address in interface["addresses"]:
            if "/" in address:
                ip = address.split("/")[0]

                if "." in ip:
                    return ip

    return None


def send_request(server_url, endpoint, data):
    url = f"{server_url}{endpoint}"

    payload = json.dumps(data).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)

    except HTTPError as error:
        try:
            body = error.read().decode("utf-8")
            return error.code, json.loads(body)
        except Exception:
            return error.code, {"error": str(error)}

    except URLError as error:
        return None, {"error": str(error)}

    except Exception as error:
        return None, {"error": str(error)}


def build_terminal_info(identity):
    return {
        "name": identity["name"],
        "mac": identity["mac"],
        "hostname": socket.gethostname(),
        "ip": get_local_ip()
    }


def register(server_url, identity, logger):
    data = build_terminal_info(identity)

    logger.info("Enregistrement du terminal : %s", identity["name"])

    status, response = send_request(
        server_url,
        REGISTER_ENDPOINT,
        data
    )

    if status == 201:
        logger.info(
            "Terminal enregistré : %s",
            response.get("terminal_id", identity["name"])
        )
        return True

    logger.error(
        "Échec de l'enregistrement (%s) : %s",
        status,
        response
    )

    return False


def heartbeat(server_url, identity, logger):
    data = {
        "name": identity["name"],
        "mac": identity["mac"]
    }

    status, response = send_request(
        server_url,
        HEARTBEAT_ENDPOINT,
        data
    )

    if status == 200:
        logger.info(
            "Heartbeat OK : %s",
            response.get("last_seen", "inconnu")
        )
        return True

    logger.error(
        "Heartbeat échoué (%s) : %s",
        status,
        response
    )

    return False


def main():
    setup_logging()
    logger = logging.getLogger("tcds-client")

    logger.info("TCDS Client %s démarrage", VERSION)

    try:
        server_host, server_port = load_config()
    except Exception as error:
        logger.error("Configuration invalide : %s", error)
        return 1

    server_url = f"http://{server_host}:{server_port}"

    logger.info("Serveur TCDS : %s", server_url)

    identity = tcds_identity.get_identity()

    logger.info("Terminal : %s", identity["name"])
    logger.info("MAC : %s", identity["mac"])

    if not register(server_url, identity, logger):
        logger.error("Impossible d'enregistrer le terminal")
        return 1

    logger.info("Client TCDS actif")

    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        heartbeat(server_url, identity, logger)


if __name__ == "__main__":
    sys.exit(main())
