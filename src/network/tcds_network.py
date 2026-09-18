#!/usr/bin/env python3

import ipaddress
import logging
import socket
import subprocess


logger = logging.getLogger("tcds-network")


def run_command(command):
    """Execute une commande système et retourne sa sortie."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.error("Commande échouée : %s", error)
        return ""


def get_interfaces():
    """Retourne les interfaces réseau et leurs adresses."""
    output = run_command(["ip", "-br", "addr"])

    interfaces = []

    for line in output.splitlines():
        parts = line.split()

        if len(parts) < 3:
            continue

        name = parts[0]
        state = parts[1]
        addresses = parts[2:]

        interfaces.append({
            "name": name,
            "state": state,
            "addresses": addresses,
        })

    return interfaces


def get_default_gateway():
    """Retourne la passerelle IPv4 par défaut."""
    output = run_command(["ip", "-4", "route", "show", "default"])

    if not output:
        return None

    parts = output.split()

    try:
        return parts[parts.index("via") + 1]
    except (ValueError, IndexError):
        return None


def get_dns_servers():
    """Retourne les serveurs DNS configurés."""
    dns_servers = []

    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as resolv:
            for line in resolv:
                line = line.strip()

                if line.startswith("nameserver "):
                    dns_servers.append(line.split()[1])
    except OSError as error:
        logger.error("Impossible de lire /etc/resolv.conf : %s", error)

    return dns_servers


def check_gateway(gateway):
    """Vérifie si la passerelle est une adresse IPv4 valide."""
    if not gateway:
        return False

    try:
        ipaddress.IPv4Address(gateway)
        return True
    except ipaddress.AddressValueError:
        return False


def get_network_status():
    """Retourne l'état général du réseau."""
    interfaces = get_interfaces()
    gateway = get_default_gateway()
    dns_servers = get_dns_servers()

    active_interfaces = [
        interface
        for interface in interfaces
        if interface["state"] == "UP"
        and interface["name"] != "lo"
    ]

    return {
        "interfaces": interfaces,
        "active_interfaces": active_interfaces,
        "gateway": gateway,
        "gateway_valid": check_gateway(gateway),
        "dns_servers": dns_servers,
        "network_available": bool(active_interfaces and gateway),
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger.info("TCDS Network 0.1.0")

    status = get_network_status()

    logger.info(
        "Interfaces actives : %d",
        len(status["active_interfaces"])
    )

    for interface in status["active_interfaces"]:
        logger.info(
            "%s : %s",
            interface["name"],
            ", ".join(interface["addresses"])
        )

    logger.info(
        "Passerelle : %s",
        status["gateway"] or "aucune"
    )

    logger.info(
        "DNS : %s",
        ", ".join(status["dns_servers"]) or "aucun"
    )

    logger.info(
        "Réseau disponible : %s",
        "oui" if status["network_available"] else "non"
    )


if __name__ == "__main__":
    main()
