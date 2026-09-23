#!/usr/bin/env python3

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


identity_module = types.ModuleType("identity")
identity_module.get_identity = lambda: "TCDS-TEST01"
sys.modules["identity"] = identity_module

import client.tcds_client as tcds_client


class TestLocalConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "tcds-config.json"

        self.original_config_file = tcds_client.LOCAL_CONFIG_FILE
        tcds_client.LOCAL_CONFIG_FILE = str(self.config_file)

    def tearDown(self):
        tcds_client.LOCAL_CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def test_missing_config_returns_none(self):
        config = tcds_client.load_local_config()

        self.assertIsNone(config)

    def test_valid_config_is_loaded(self):
        expected_config = {
            "terminal_id": "TCDS-TEST01",
            "config_version": 3,
            "settings": {
                "log_level": "DEBUG",
                "session_enabled": False,
                "ui_enabled": False,
            },
        }

        self.config_file.write_text(
            json.dumps(expected_config),
            encoding="utf-8",
        )

        config = tcds_client.load_local_config()

        self.assertEqual(config, expected_config)

    def test_invalid_json_returns_none(self):
        self.config_file.write_text(
            "{invalid json",
            encoding="utf-8",
        )

        config = tcds_client.load_local_config()

        self.assertIsNone(config)


class TestApplyConfig(unittest.TestCase):

    def test_log_level_is_applied(self):
        config = {
            "config_version": 1,
            "settings": {
                "log_level": "DEBUG",
                "session_enabled": False,
                "ui_enabled": False,
            },
        }

        tcds_client.apply_config(config)

        self.assertEqual(
            tcds_client.log.level,
            tcds_client.logging.DEBUG,
        )


if __name__ == "__main__":
    unittest.main()
