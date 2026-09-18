#!/usr/bin/env python3

import configparser
import logging
import platform
import socket
import sys
import time
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


CONFIG_FILE = "/etc/tcds/tcds.conf"
VERSION = "0.3.0"


def load_config():
    config = configparser.ConfigParser()

    if Path(CONFIG_FILE).exists():
        config.read(CONFIG_FILE)

    return config


def setup_logging(config):
    level_name = config.get("core", "log_level", fallback="INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )


def get_system_info():
    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version()
    }


def log_identity(logger):
    identity = tcds_identity.get_identity()

    if not identity:
        logger.error("Identité du terminal indisponible")
        return None

    logger.info("Terminal : %s", identity["name"])
    logger.info("MAC : %s", identity["mac"])

    return identity


def log_network_status(logger):
    status = tcds_network.get_network_status()

    if status["network_available"]:
        logger.info("Réseau : disponible")
    else:
        logger.warning("Réseau : indisponible")

    for interface in status["active_interfaces"]:
        logger.info("Interface : %s", interface["name"])

        for address in interface["addresses"]:
            logger.info("Adresse : %s", address)

    logger.info("Passerelle : %s", status["gateway"] or "aucune")

    if status["dns_servers"]:
        for dns in status["dns_servers"]:
            logger.info("DNS : %s", dns)
    else:
        logger.info("DNS : aucun")


def main():
    config = load_config()
    setup_logging(config)

    logger = logging.getLogger("tcds-core")

    logger.info("TCDS Core %s démarrage", VERSION)

    system = get_system_info()

    for key, value in system.items():
        logger.info("%s: %s", key, value)

    identity = log_identity(logger)

    if not identity:
        logger.error("TCDS Core ne peut pas continuer sans identité")
        return 1

    network_enabled = config.getboolean(
        "network",
        "enabled",
        fallback=True
    )

    session_enabled = config.getboolean(
        "session",
        "enabled",
        fallback=False
    )

    ui_enabled = config.getboolean(
        "ui",
        "enabled",
        fallback=False
    )

    logger.info(
        "Réseau : %s",
        "activé" if network_enabled else "désactivé"
    )

    logger.info(
        "Session : %s",
        "activée" if session_enabled else "désactivée"
    )

    logger.info(
        "Interface : %s",
        "activée" if ui_enabled else "désactivée"
    )

    if network_enabled:
        log_network_status(logger)

    logger.info("TCDS Core actif")

    try:
        while True:
            time.sleep(30)

    except KeyboardInterrupt:
        logger.info("Arrêt de TCDS Core")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
