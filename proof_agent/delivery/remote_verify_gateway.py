from __future__ import annotations

import argparse
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.request import urlopen

VERIFY_REMOTE_CHAT_BASE = "/__proofagent_chat__/"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class GatewayConfig:
    def __init__(
        self,
        *,
        backend_origin: str,
        dashboard_origin: str,
        chat_origin: str,
        chat_base: str | None = None,
    ) -> None:
        self.backend_origin = backend_origin.rstrip("/")
        self.dashboard_origin = dashboard_origin.rstrip("/")
        self.chat_origin = chat_origin.rstrip("/")
        self.chat_base = _normalize_base(chat_base) if chat_base is not None else None


def _normalize_base(base: str) -> str:
    normalized = base.strip("/")
    if not normalized:
        raise ValueError("Chat base must contain a non-slash path segment.")
    return f"/{normalized}/"


def make_handler(config: GatewayConfig) -> type[BaseHTTPRequestHandler]:
    class VerifyRemoteGatewayHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self) -> None:
            self._proxy()

        def do_HEAD(self) -> None:
            self._proxy()

        def do_POST(self) -> None:
            self._proxy()

        def do_PUT(self) -> None:
            self._proxy()

        def do_PATCH(self) -> None:
            self._proxy()

        def do_DELETE(self) -> None:
            self._proxy()

        def do_OPTIONS(self) -> None:
            self._proxy()

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[verify-gateway] {self.address_string()} - {format % args}")

        def _proxy(self) -> None:
            if self.headers.get("Upgrade"):
                self.send_error(
                    HTTPStatus.UPGRADE_REQUIRED,
                    "WebSocket proxying is not supported by the verification gateway.",
                )
                return

            # Neither SPA declares a favicon. Browsers otherwise synthesize an
            # ambiguous root request that the path-only gateway cannot attribute.
            if urlsplit(self.path).path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return

            target_url = self._target_url()
            body = self._request_body()
            request = Request(
                target_url,
                data=body,
                headers=self._forward_headers(),
                method=self.command,
            )
            try:
                with urlopen(request, timeout=60) as response:
                    self.send_response(response.status)
                    self._send_response_headers(response.headers.items())
                    self.end_headers()
                    if self.command != "HEAD":
                        shutil.copyfileobj(response, self.wfile)
            except HTTPError as exc:
                self.send_response(exc.code)
                self._send_response_headers(exc.headers.items())
                self.end_headers()
                if self.command != "HEAD":
                    shutil.copyfileobj(exc, self.wfile)
            except URLError as exc:
                self.send_error(
                    HTTPStatus.BAD_GATEWAY,
                    f"Upstream unavailable for {target_url}: {exc.reason}",
                )

        def _target_url(self) -> str:
            request_target = self.path if self.path.startswith("/") else f"/{self.path}"
            parsed_target = urlsplit(request_target)
            path = parsed_target.path or "/"
            query = f"?{parsed_target.query}" if parsed_target.query else ""
            if path == "/api" or path.startswith("/api/"):
                return f"{config.backend_origin}{path}{query}"

            is_public_chat_path = (
                path == "/operator"
                or path.startswith("/operator/")
                or path == "/customer"
                or path.startswith("/customer/")
            )
            chat_base = config.chat_base
            if chat_base is not None and is_public_chat_path:
                upstream_path = f"{chat_base}{path.lstrip('/')}"
                return f"{config.chat_origin}{upstream_path}{query}"
            if chat_base is not None and (
                path == chat_base.rstrip("/") or path.startswith(chat_base)
            ):
                return f"{config.chat_origin}{path}{query}"
            if is_public_chat_path:
                return f"{config.chat_origin}{path}{query}"
            return f"{config.dashboard_origin}{path}{query}"

        def _request_body(self) -> bytes | None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return None
            length = int(raw_length)
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _forward_headers(self) -> dict[str, str]:
            headers: dict[str, str] = {}
            for key, value in self.headers.items():
                lowered = key.lower()
                if lowered == "host" or lowered in HOP_BY_HOP_HEADERS:
                    continue
                headers[key] = value
            return headers

        def _send_response_headers(self, items: Any) -> None:
            for key, value in items:
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)

    return VerifyRemoteGatewayHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Proof Agent remote verification gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--backend-origin", required=True)
    parser.add_argument("--dashboard-origin", required=True)
    parser.add_argument("--chat-origin", required=True)
    parser.add_argument("--chat-base", default=VERIFY_REMOTE_CHAT_BASE)
    args = parser.parse_args()
    config = GatewayConfig(
        backend_origin=args.backend_origin,
        dashboard_origin=args.dashboard_origin,
        chat_origin=args.chat_origin,
        chat_base=args.chat_base,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(config))
    print(f"[verify-gateway] serving http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
