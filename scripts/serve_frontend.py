from __future__ import annotations

import argparse
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class FrontendHandler(BaseHTTPRequestHandler):
    dist_dir: Path
    api_target: str

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy()
            return
        self.serve_static()

    def do_POST(self) -> None:
        self.proxy()

    def do_PUT(self) -> None:
        self.proxy()

    def do_DELETE(self) -> None:
        self.proxy()

    def do_OPTIONS(self) -> None:
        self.proxy()

    def serve_static(self) -> None:
        request_path = urlsplit(self.path).path.lstrip("/")
        candidate = (self.dist_dir / request_path).resolve()
        try:
            candidate.relative_to(self.dist_dir)
        except ValueError:
            self.send_error(403)
            return
        if not candidate.is_file():
            candidate = self.dist_dir / "index.html"
        if not candidate.is_file():
            self.send_error(404)
            return

        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def proxy(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        url = f"{self.api_target}{self.path}"
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        request = Request(url, data=body if body else None, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=60) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            for key, value in error.headers.items():
                if key.lower() not in {"transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except URLError as error:
            self.send_error(502, f"API proxy failed: {error.reason}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--api-target", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    handler = FrontendHandler
    handler.dist_dir = Path(args.dist).resolve()
    handler.api_target = args.api_target.rstrip("/")
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {handler.dist_dir} at http://{args.host}:{args.port}")
    print(f"Proxying /api to {handler.api_target}")
    server.serve_forever()


if __name__ == "__main__":
    main()
