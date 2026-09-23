#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import server.database as database
from starlette.testclient import TestClient

from server.tcds_server import app


class TestAPI(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"

        self.original_database_file = database.DATABASE_FILE
        database.DATABASE_FILE = self.database_file

        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        database.DATABASE_FILE = self.original_database_file
        self.temp_dir.cleanup()

    def test_status(self):
        response = self.client.get("/api/v1/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "tcds-server",
                "version": "0.1.0",
            },
        )

    def test_register_terminal(self):
        terminal = {
            "terminal_id": "TCDS-TEST01",
            "hostname": "test-terminal",
            "mac_address": "00:11:22:33:44:55",
            "ip_address": "192.168.1.100",
            "architecture": "aarch64",
            "client_version": "0.1.0",
        }

        response = self.client.post(
            "/api/v1/terminals/register",
            json=terminal,
        )

        self.assertEqual(response.status_code, 201)

        body = response.json()

        self.assertEqual(body["status"], "registered")
        self.assertEqual(
            body["terminal"]["terminal_id"],
            "TCDS-TEST01",
        )
        self.assertTrue(body["terminal"]["online"])

    def test_register_creates_default_config(self):
        terminal = {
            "terminal_id": "TCDS-TEST02",
            "hostname": "test-terminal",
            "mac_address": "00:11:22:33:44:66",
            "ip_address": "192.168.1.101",
            "architecture": "aarch64",
            "client_version": "0.1.0",
        }

        response = self.client.post(
            "/api/v1/terminals/register",
            json=terminal,
        )

        self.assertEqual(response.status_code, 201)

        response = self.client.get(
            "/api/v1/terminals/TCDS-TEST02/config"
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertEqual(body["config_version"], 1)
        self.assertEqual(
            body["settings"],
            {
                "log_level": "INFO",
                "session_enabled": False,
                "ui_enabled": False,
            },
        )

    def test_update_config_increments_version(self):
        terminal = {
            "terminal_id": "TCDS-TEST03",
            "hostname": "test-terminal",
            "mac_address": "00:11:22:33:44:77",
            "ip_address": "192.168.1.102",
            "architecture": "aarch64",
            "client_version": "0.1.0",
        }

        response = self.client.post(
            "/api/v1/terminals/register",
            json=terminal,
        )

        self.assertEqual(response.status_code, 201)

        new_config = {
            "log_level": "DEBUG",
            "session_enabled": True,
            "ui_enabled": False,
        }

        response = self.client.put(
            "/api/v1/terminals/TCDS-TEST03/config",
            json=new_config,
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertEqual(body["config_version"], 2)
        self.assertEqual(body["settings"], new_config)

        response = self.client.get(
            "/api/v1/terminals/TCDS-TEST03/config"
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertEqual(body["config_version"], 2)
        self.assertEqual(body["settings"], new_config)

    def test_invalid_config_returns_422(self):
        terminal = {
            "terminal_id": "TCDS-TEST04",
            "hostname": "test-terminal",
            "mac_address": "00:11:22:33:44:88",
            "ip_address": "192.168.1.103",
            "architecture": "aarch64",
            "client_version": "0.1.0",
        }

        response = self.client.post(
            "/api/v1/terminals/register",
            json=terminal,
        )

        self.assertEqual(response.status_code, 201)

        invalid_config = {
            "log_level": "INVALID",
            "session_enabled": False,
            "ui_enabled": False,
        }

        response = self.client.put(
            "/api/v1/terminals/TCDS-TEST04/config",
            json=invalid_config,
        )

        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/v1/terminals/TCDS-TEST04/config"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config_version"], 1)
        self.assertEqual(
            response.json()["settings"]["log_level"],
            "INFO",
        )

    def test_unknown_terminal_returns_404(self):
        response = self.client.get(
            "/api/v1/terminals/DOES-NOT-EXIST/config"
        )

        self.assertEqual(response.status_code, 404)

    def test_heartbeat_returns_config_version(self):
        terminal = {
            "terminal_id": "TCDS-TEST05",
            "hostname": "test-terminal",
            "mac_address": "00:11:22:33:44:99",
            "ip_address": "192.168.1.104",
            "architecture": "aarch64",
            "client_version": "0.1.0",
        }

        response = self.client.post(
            "/api/v1/terminals/register",
            json=terminal,
        )

        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            "/api/v1/terminals/TCDS-TEST05/heartbeat"
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertEqual(body["status"], "ok")
        self.assertEqual(
            body["terminal_id"],
            "TCDS-TEST05",
        )
        self.assertEqual(body["config_version"], 1)


if __name__ == "__main__":
    unittest.main()
