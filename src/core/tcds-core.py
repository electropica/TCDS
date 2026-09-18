#!/usr/bin/env python3

import configparser
import logging
import platform
import socket
import time

CONFIG_FILE = "/etc/tcds/tcds.conf"
VERSION = "0.1.0"


def load_config():
    config = configparser.ConfigParser()

    if not config.read(CONFIG_FILE):
        raise FileNotFoundError(
            f"Configuration introuvable : {CONFIG_FILE}"
        )

    return config


def setup_logging(config):
    log_level = config.get(
        "core",
        "log_level",
        fallback="INFO"
    ).upper()

    level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )


def get_system_info():
    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
    }


def main():
    config = load_config()
    setup_logging(config)

    logger = logging.getLogger("tcds-core")

    version = config.get(
        "core",
        "version",
        fallback=VERSION
    )

    logger.info("TCDS Core %s démarrage", version)

    info = get_system_info()

    for key, value in info.items():
        logger.info("%s: %s", key, value)

    network_enabled = config.getboolean(
        "network",
        "enabled",
        fallback=False
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

    logger.info("Réseau : %s", "activé" if network_enabled else "désactivé")
    logger.info("Session : %s", "activée" if session_enabled else "désactivée")
    logger.info("Interface : %s", "activée" if ui_enabled else "désactivée")

    logger.info("TCDS Core actif")

    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
