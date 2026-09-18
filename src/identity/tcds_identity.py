#!/usr/bin/env python3

import configparser
import logging
import subprocess
from pathlib import Path

IDENTITY_FILE = Path("/etc/tcds/identity")
VERSION = "0.1.0"


def get_mac():
    """Retourne la MAC de la première interface réseau physique active."""
    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True,
            text=True,
            check=True
        )

        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 17:
                continue

            interface = parts[1].rstrip(":")
            mac = parts[16]

            if interface == "lo":
                continue

            if mac == "00:00:00:00:00:00":
                continue

            return mac.lower()

    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    return None


def generate_name(mac):
    """Construit le nom TCDS à partir des 6 derniers caractères de la MAC."""
    if not mac:
        return None

    compact_mac = mac.replace(":", "").replace("-", "").upper()

    if len(compact_mac) != 12:
        return None

    return f"TCDS-{compact_mac[-6:]}"


def save_identity(name, mac):
    """Enregistre l'identité locale du terminal."""
    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)

    config = configparser.ConfigParser()
    config["identity"] = {
        "name": name,
        "mac": mac
    }

    with IDENTITY_FILE.open("w") as file:
        config.write(file)


def load_identity():
    """Charge l'identité locale si elle existe."""
    if not IDENTITY_FILE.exists():
        return None

    config = configparser.ConfigParser()
    config.read(IDENTITY_FILE)

    if "identity" not in config:
        return None

    name = config["identity"].get("name")
    mac = config["identity"].get("mac")

    if not name or not mac:
        return None

    return {
        "name": name,
        "mac": mac
    }


def get_identity():
    """Retourne l'identité existante ou la crée automatiquement."""
    identity = load_identity()

    if identity:
        return identity

    mac = get_mac()

    if not mac:
        return None

    name = generate_name(mac)

    if not name:
        return None

    save_identity(name, mac)

    return {
        "name": name,
        "mac": mac
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger = logging.getLogger("tcds-identity")

    logger.info("TCDS Identity %s", VERSION)

    identity = get_identity()

    if not identity:
        logger.error("Impossible de déterminer l'identité du terminal")
        return 1

    logger.info("Nom : %s", identity["name"])
    logger.info("MAC : %s", identity["mac"])
    logger.info("Fichier : %s", IDENTITY_FILE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
