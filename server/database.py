#!/usr/bin/env python3

import sqlite3
from pathlib import Path

DATABASE_FILE = Path("/opt/tcds/data/tcds.db")


def get_connection():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row

    return connection


def init_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS terminals (
                terminal_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                mac_address TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                architecture TEXT NOT NULL,
                client_version TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS terminal_config (
                terminal_id TEXT PRIMARY KEY,
                config_version INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (terminal_id)
                    REFERENCES terminals(terminal_id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.commit()
