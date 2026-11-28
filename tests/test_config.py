"""Tests for secret loading configuration."""

import importlib
import sys
import types
import unittest
from unittest import mock


class ConfigSecretTest(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("config", None)
        sys.modules.pop("local_secrets", None)
        cv2 = types.ModuleType("cv2")
        cv2.setNumThreads = lambda *_args: None
        cv2.setUseOptimized = lambda *_args: None
        self.cv2_patch = mock.patch.dict(sys.modules, {"cv2": cv2})
        self.cv2_patch.start()

    def tearDown(self):
        self.cv2_patch.stop()
        sys.modules.pop("config", None)
        sys.modules.pop("local_secrets", None)

    def test_environment_key_is_used_when_local_secret_is_empty(self):
        local_secrets = types.ModuleType("local_secrets")
        local_secrets.GROQ_API_KEY = ""
        sys.modules["local_secrets"] = local_secrets

        with mock.patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "environment-test-key"},
            clear=False,
        ):
            config = importlib.import_module("config")

        self.assertEqual(config.GROQ_API_KEY, "environment-test-key")

    def test_local_secret_takes_precedence_over_environment(self):
        local_secrets = types.ModuleType("local_secrets")
        local_secrets.GROQ_API_KEY = "local-test-key"
        sys.modules["local_secrets"] = local_secrets

        with mock.patch.dict(
            "os.environ",
            {"GROQ_API_KEY": "environment-test-key"},
            clear=False,
        ):
            config = importlib.import_module("config")

        self.assertEqual(config.GROQ_API_KEY, "local-test-key")


if __name__ == "__main__":
    unittest.main()
