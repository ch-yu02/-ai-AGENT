import unittest
from unittest.mock import patch

from backend.app.main import _cors_allow_origins


class MainAppConfigTest(unittest.TestCase):
    def test_cors_origins_include_dev_and_app_preview_ports(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            origins = _cors_allow_origins()

        self.assertIn("http://localhost:5173", origins)
        self.assertIn("http://127.0.0.1:5173", origins)
        self.assertIn("http://localhost:4173", origins)
        self.assertIn("http://127.0.0.1:4173", origins)

    def test_cors_origins_include_configured_ports_and_extra_origins(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "FRONTEND_PREVIEW_PORT": "4180",
                "CORS_ALLOW_ORIGINS": "http://192.168.1.10:4180/",
            },
            clear=True,
        ):
            origins = _cors_allow_origins()

        self.assertIn("http://localhost:4180", origins)
        self.assertIn("http://127.0.0.1:4180", origins)
        self.assertIn("http://192.168.1.10:4180", origins)


if __name__ == "__main__":
    unittest.main()
