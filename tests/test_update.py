import hashlib
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import tests  # noqa: F401  (sets up the import path)

try:
    import update
except ImportError:  # no PySide6
    update = None

PAYLOAD = b"a new AppImage " * 100_000


class Server(http.server.BaseHTTPRequestHandler):
    """Stands in for GitHub: /latest is the API's answer, anything else the download."""
    release = None  # the JSON to answer with; None answers 404
    payload = PAYLOAD

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/latest" and Server.release is None:
            self.send_error(404)
            return
        body = json.dumps(Server.release).encode() if self.path == "/latest" else Server.payload
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:
            pass  # a canceled download


def release(**asset):
    return {"tag_name": "v0.2.0", "html_url": "https://github.com/x/y/releases/tag/v0.2.0", "body": "notes", "assets": [
        {"name": "other"},
        {"name": update.ASSET, "browser_download_url": "https://example.com/a", "size": len(PAYLOAD),
         "digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(), **asset},
    ]}


@unittest.skipUnless(update, "needs PySide6")
class Update(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.latest, update.LATEST = update.LATEST, cls.base + "/latest"

    @classmethod
    def tearDownClass(cls):
        update.LATEST = cls.latest
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Server.release, Server.payload = release(), PAYLOAD
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.target = Path(folder.name) / "App.AppImage"
        self.target.write_bytes(b"old")
        self.target.chmod(0o644)

    def test_versions_compare_by_their_numbers(self):
        self.assertEqual(update.numbers("1.2.3"), (1, 2, 3))
        self.assertEqual(update.numbers("1.2.3-4-gabc-dirty"), (1, 2, 3))
        self.assertEqual(update.numbers("5332231-dirty"), ())  # a bare commit is older than any release
        self.assertEqual(update.numbers(None), ())
        self.assertGreater(update.numbers("1.10.0"), update.numbers("1.9.9"))

    def test_latest(self):
        found = update.latest()
        self.assertEqual((found.version, found.url, found.size), ("0.2.0", "https://example.com/a", len(PAYLOAD)))
        self.assertEqual(found.sha256, hashlib.sha256(PAYLOAD).hexdigest())
        Server.release = None
        self.assertIsNone(update.latest())
        Server.release = release(browser_download_url="http://example.com/a")  # not https
        self.assertIsNone(update.latest().url)
        Server.release = {"tag_name": "v1", "html_url": "https://x", "assets": []}
        self.assertIsNone(update.latest().url)
        Server.release = {"unexpected": 1}
        with self.assertRaises(ValueError):
            update.latest()

    def downloadable(self, **changes):
        return update.latest()._replace(**{"url": self.base + "/file", **changes})

    def test_install_replaces_the_file(self):
        seen = []
        update.install(self.downloadable(), self.target, lambda done, total: seen.append((done, total)))
        self.assertEqual(self.target.read_bytes(), PAYLOAD)
        self.assertTrue(self.target.stat().st_mode & 0o111)
        self.assertEqual(seen[-1], (len(PAYLOAD), len(PAYLOAD)))

    def test_install_leaves_the_file_alone_when_it_fails(self):
        refused = self.base.replace(str(self.server.server_port), "1") + "/file"
        for bad, error in ((self.downloadable(sha256="0" * 64), ValueError), (self.downloadable(size=5), ValueError),
                           (self.downloadable(url=refused), OSError)):
            with self.assertRaises(error):
                update.install(bad, self.target)
            self.assertEqual(self.target.read_bytes(), b"old")
            self.assertEqual([path.name for path in self.target.parent.iterdir()], [self.target.name])
        with self.assertRaises(update.Canceled):
            update.install(self.downloadable(), self.target, canceled=lambda: True)
        self.assertEqual(self.target.read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
