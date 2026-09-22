#!/usr/bin/env python3

import hashlib
from pathlib import Path

IDENTITY_FILE = Path("/opt/tcds/config/identity")


def get_mac_address():
    mac_file = Path("/sys/class/net/eth0/address")

    if not mac_file.exists():
        raise RuntimeError("Interface eth0 introuvable")

    return mac_file.read_text().strip().lower()


def generate_identity(mac):
    digest = hashlib.sha256(mac.encode()).hexdigest().upper()
    return f"TCDS-{digest[:6]}"


def get_identity():
    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if IDENTITY_FILE.exists():
        identity = IDENTITY_FILE.read_text().strip()

        if identity:
            return identity

    mac = get_mac_address()
    identity = generate_identity(mac)

    IDENTITY_FILE.write_text(identity + "\n")

    return identity


if __name__ == "__main__":
    print(get_identity())
