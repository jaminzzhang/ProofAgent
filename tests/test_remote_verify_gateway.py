from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from proof_agent.delivery.remote_verify_gateway import GatewayConfig
from proof_agent.delivery.remote_verify_gateway import make_handler


@contextmanager
def upstream_server(label: str) -> Iterator[str]:
    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = f"{label}:{self.path}".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def gateway_server(config: GatewayConfig) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def read_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def test_remote_verify_gateway_routes_api_chat_and_dashboard_paths() -> None:
    with (
        upstream_server("backend") as backend_origin,
        upstream_server("dashboard") as dashboard_origin,
        upstream_server("chat") as chat_origin,
        gateway_server(
            GatewayConfig(
                backend_origin=backend_origin,
                dashboard_origin=dashboard_origin,
                chat_origin=chat_origin,
            )
        ) as gateway_origin,
    ):
        assert read_text(f"{gateway_origin}/api/health") == "backend:/api/health"
        assert read_text(f"{gateway_origin}/operator") == "chat:/operator"
        assert read_text(f"{gateway_origin}/runs/run_1") == "dashboard:/runs/run_1"
