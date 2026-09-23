#!/usr/bin/env python3

import configparser
import json
import logging
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/tcds/identity")

from identity import get_identity

VERSION = "0.1.0"

CONFIG_FILE = "/opt/tcds/config/tcds-client.conf"
LOCAL_CONFIG_FILE = "/opt/tcds/config/tcds-config.json"
HEARTBEAT_INTERVAL = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("tcds-client")


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    if not config.has_option("server", "url"):
        raise RuntimeError(
            f"Adresse du serveur absente de {CONFIG_FILE}"
        )

    return config.get("server", "url").rstrip("/")


def get_mac_address():
    mac_file = "/sys/class/net/eth0/address"

    try:
        with open(mac_file, "r", encoding="utf-8") as file:
            return file.read().strip().lower()
    except OSError as error:
        raise RuntimeError(
            "Impossible de lire l'adresse MAC de eth0"
        ) from error


def get_ip_address():
    result = subprocess.run(
        [
            "/usr/sbin/ip",
            "-4",
            "-o",
            "addr",
            "show",
            "dev",
            "eth0",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    for field in result.stdout.split():
        if "/" in field and field.count(".") == 3:
            return field.split("/")[0]

    raise RuntimeError(
        "Aucune adresse IPv4 trouvée sur eth0"
    )


def register(
    server_url,
    terminal_id,
    hostname,
    mac_address,
    ip_address,
):
    data = {
        "terminal_id": terminal_id,
        "hostname": hostname,
        "mac_address": mac_address,
        "ip_address": ip_address,
        "architecture": platform.machine(),
        "client_version": VERSION,
    }

    payload = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        f"{server_url}/api/v1/terminals/register",
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))

    log.info("Registration OK: %s", body)


def get_remote_config(server_url, terminal_id):
    request = urllib.request.Request(
        f"{server_url}/api/v1/terminals/{terminal_id}/config",
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def load_local_config():
    try:
        with open(LOCAL_CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError:
        log.info("Aucune configuration locale disponible")
        return None
    except (OSError, json.JSONDecodeError) as error:
        log.warning(
            "Impossible de charger la configuration locale: %s",
            error,
        )
        return None

    log.info(
        "Configuration locale chargée: version=%s",
        config.get("config_version"),
    )

    return config


def save_local_config(config):
    with open(LOCAL_CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)
        file.write("\n")

    log.info(
        "Configuration locale sauvegardée: version=%s",
        config.get("config_version"),
    )


def apply_config(config):
    settings = config.get("settings", {})
    log_level = settings.get("log_level", "INFO").upper()

    valid_levels = {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }

    if log_level not in valid_levels:
        log.warning(
            "Niveau de log invalide: %s, utilisation de INFO",
            log_level,
        )
        log_level = "INFO"

    log.setLevel(getattr(logging, log_level))

    log.info(
        "Configuration appliquée: log_level=%s",
        log_level,
    )


def heartbeat(server_url, terminal_id):
    request = urllib.request.Request(
        f"{server_url}/api/v1/terminals/{terminal_id}/heartbeat",
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))

    log.info(
        "Heartbeat OK: last_seen=%s",
        body.get("last_seen"),
    )

    return body


def main():
    hostname = socket.gethostname()
    identity = get_identity()
    server_url = load_config()
    mac_address = get_mac_address()
    ip_address = get_ip_address()

    log.info("TCDS Client %s starting", VERSION)
    log.info("Identity: %s", identity)
    log.info("Hostname: %s", hostname)
    log.info("MAC: %s", mac_address)
    log.info("IP: %s", ip_address)
    log.info("Architecture: %s", platform.machine())
    log.info("Kernel: %s", platform.release())
    log.info("Server: %s", server_url)

    local_config = load_local_config()
    config_version = None

    if local_config is not None:
        apply_config(local_config)
        config_version = local_config.get("config_version")

    while True:
        try:
            register(
                server_url,
                identity,
                hostname,
                mac_address,
                ip_address,
            )
            break
        except urllib.error.URLError as error:
            log.error("Registration failed: %s", error)
        except Exception as error:
            log.error("Registration failed: %s", error)

        log.info("Retrying registration in %d seconds", HEARTBEAT_INTERVAL)
        time.sleep(HEARTBEAT_INTERVAL)

    try:
        config = get_remote_config(server_url, identity)
        save_local_config(config)
        apply_config(config)
        config_version = config.get("config_version")
    except urllib.error.URLError as error:
        log.error("Configuration retrieval failed: %s", error)
    except Exception as error:
        log.error("Configuration retrieval failed: %s", error)

    while True:
        time.sleep(HEARTBEAT_INTERVAL)

        try:
            heartbeat_data = heartbeat(server_url, identity)
            remote_config_version = heartbeat_data.get("config_version")

            if (
                remote_config_version is not None
                and remote_config_version != config_version
            ):
                log.info(
                    "Nouvelle configuration détectée: version=%s",
                    remote_config_version,
                )

                config = get_remote_config(server_url, identity)
                save_local_config(config)
                apply_config(config)
                config_version = config.get("config_version")

        except urllib.error.URLError as error:
            log.error("Heartbeat failed: %s", error)
        except Exception as error:
            log.error("Heartbeat failed: %s", error)


if __name__ == "__main__":
    main()
