"""A tiny local HTTP server that pretends to be thumbnails.libretro.com and the Steam CDN (tests never use the internet)."""
import http.server
import threading
import urllib.parse

def _png() -> bytes:
    """A real (decodable) 2x3 PNG so QML can load it."""
    import struct
    import zlib

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xc8\x20\x30" * 2 for _ in range(3))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 3, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 64


class Fake:
    def __init__(self):
        self.files: dict[str, bytes] = {}      # path (unquoted) -> body
        self.flaky: dict[str, int] = {}        # path -> number of 503s to serve first
        self.hits: list[str] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = urllib.parse.unquote(self.path)
                outer.hits.append(path)
                if outer.flaky.get(path, 0) > 0:
                    outer.flaky[path] -= 1
                    self.send_response(503)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                if path in outer.files:
                    body = outer.files[path]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def listing(self, folder: str, names: list[str]):
        rows = "".join(f'<tr><td><a href="{urllib.parse.quote(n)}">{n}</a></td></tr>' for n in names)
        self.files[f"/{folder}/Named_Boxarts/"] = f"<html><body><table>{rows}</table></body></html>".encode()
        for n in names:
            self.files[f"/{folder}/Named_Boxarts/{n}"] = PNG

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
