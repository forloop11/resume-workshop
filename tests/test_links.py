import http.server
import threading
import unittest

import tests  # noqa: F401  (sets up the import path)

try:
    import links
except ImportError:  # no PySide6
    links = None


class Site(http.server.BaseHTTPRequestHandler):
    """Answers /200, /404 and so on with that status; /moved redirects to /200."""

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/200")
        else:
            self.send_response(int(self.path.strip("/")))
        self.send_header("Content-Length", "0")
        self.end_headers()


def site():
    """Starts a Site; returns its address and the function that stops it."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", lambda: (server.shutdown(), server.server_close())


@unittest.skipUnless(links, "needs PySide6")
class Links(unittest.TestCase):
    def test_what_is_an_address(self):
        self.assertEqual(links.address(" example.com/me "), "https://example.com/me")
        self.assertEqual(links.address("http://example.com"), "http://example.com")
        for text in ("", "not an address", "file:///etc/passwd", "mailto:me@example.com", "localhost", "https://exa mple.com"):
            self.assertIsNone(links.address(text), text)

    def test_check(self):
        base, stop = site()
        self.addCleanup(stop)
        for path, result, said in (("/200", links.WORKS, "works"), ("/moved", links.WORKS, "works"), ("/404", links.BROKEN, "no such page"),
                                   ("/500", links.BROKEN, "error (500)"), ("/403", links.UNSURE, "Open it to be sure"),
                                   ("/999", links.UNSURE, "Open it to be sure")):
            self.assertEqual(links.check(base + path)[0], result, path)
            self.assertIn(said, links.check(base + path)[1])
        result, said = links.check("http://127.0.0.1:1/nothing-listens-here")
        self.assertEqual(result, links.BROKEN)
        self.assertIn("couldn't be reached", said)


if __name__ == "__main__":
    unittest.main()
