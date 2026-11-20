#!/usr/bin/env python3
"""控制台静态服务（8101）。API 在 8102，CORS 白名单仅允许 8101 来源。"""
import http.server
import os
import socketserver

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "app", "console")
PORT = int(os.environ.get("QUANT_CONSOLE_PORT", "8101"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"console http://127.0.0.1:{PORT}")
        httpd.serve_forever()
