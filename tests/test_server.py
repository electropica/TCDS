#!/usr/bin/env python3

import unittest

from fastapi import HTTPException

from server.tcds_server import validate_config


class TestValidateConfig(unittest.TestCase):

    def test_valid_config(self):
        config = {
            "log_level": "INFO",
            "session_enabled": False,
            "ui_enabled": False,
        }

        result = validate_config(config)

        self.assertEqual(result["log_level"], "INFO")
        self.assertFalse(result["session_enabled"])
        self.assertFalse(result["ui_enabled"])

    def test_log_level_is_normalized(self):
        config = {
            "log_level": "debug",
            "session_enabled": True,
            "ui_enabled": False,
        }

        result = validate_config(config)

        self.assertEqual(result["log_level"], "DEBUG")

    def test_invalid_log_level(self):
        config = {
            "log_level": "INVALID",
            "session_enabled": False,
            "ui_enabled": False,
        }

        with self.assertRaises(HTTPException) as context:
            validate_config(config)

        self.assertEqual(context.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
