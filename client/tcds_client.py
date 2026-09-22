#!/usr/bin/env python3

import logging
import platform
import socket
import sys
import time

sys.path.insert(0, "/opt/tcds/source/identity")

from identity import get_identity

VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("tcds-client")


def main():
    hostname = socket.gethostname()
    identity = get_identity()

    log.info("TCDS Client %s starting", VERSION)
    log.info("Identity: %s", identity)
    log.info("Hostname: %s", hostname)
    log.info("Architecture: %s", platform.machine())
    log.info("Kernel: %s", platform.release())

    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
