#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import server.database as database


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"

        self.original_database_file = database.DATABASE_FILE
        database.DATABASE_FILE = self.database_file

        database.init_database()

    def tearDown(self):
        database.DATABASE_FILE = self.original_database_file
        self.temp_dir.cleanup()

    def test_database_is_created(self):
        self.assertTrue(self.database_file.exists())

    def test_terminal_can_be_stored(self):
        with database.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO terminals (
                    terminal_id,
                    hostname,
                    mac_address,
                    ip_address,
                    architecture,
                    client_version,
                    last_seen,
                    online
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TCDS-TEST01",
                    "test-terminal",
                    "00:11:22:33:44:55",
                    "192.168.1.100",
                    "aarch64",
                    "0.1.0",
                    "2026-01-01T00:00:00+00:00",
                    1,
                ),
            )
            connection.commit()

            row = connection.execute(
                "SELECT * FROM terminals WHERE terminal_id = ?",
                ("TCDS-TEST01",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["hostname"], "test-terminal")
        self.assertEqual(row["architecture"], "aarch64")

    def test_configuration_can_be_stored(self):
        with database.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO terminals (
                    terminal_id,
                    hostname,
                    mac_address,
                    ip_address,
                    architecture,
                    client_version,
                    last_seen,
                    online
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TCDS-TEST02",
                    "test-terminal",
                    "00:11:22:33:44:66",
                    "192.168.1.101",
                    "aarch64",
                    "0.1.0",
                    "2026-01-01T00:00:00+00:00",
                    1,
                ),
            )

            connection.execute(
                """
                INSERT INTO terminal_config (
                    terminal_id,
                    config_version,
                    config_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "TCDS-TEST02",
                    1,
                    '{"log_level":"INFO","session_enabled":false,"ui_enabled":false}',
                    "2026-01-01T00:00:00+00:00",
                ),
            )

            connection.commit()

            row = connection.execute(
                """
                SELECT config_version, config_json
                FROM terminal_config
                WHERE terminal_id = ?
                """,
                ("TCDS-TEST02",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["config_version"], 1)
        self.assertIn('"log_level":"INFO"', row["config_json"])


if __name__ == "__main__":
    unittest.main()
