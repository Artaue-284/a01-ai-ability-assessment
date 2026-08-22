import os
import unittest
from unittest.mock import patch

import run


class LauncherSecurityTests(unittest.TestCase):
    def test_local_launcher_accepts_rotating_quick_tunnel_hosts(self):
        with patch.dict(os.environ, {"A01_ALLOWED_HOSTS": "old-host.trycloudflare.com"}, clear=False):
            run.configure_local_allowed_hosts()
            hosts = os.environ["A01_ALLOWED_HOSTS"].split(",")

        self.assertIn("old-host.trycloudflare.com", hosts)
        self.assertIn("*.trycloudflare.com", hosts)
        self.assertIn("localhost", hosts)
        self.assertIn("127.0.0.1", hosts)


if __name__ == "__main__":
    unittest.main()
