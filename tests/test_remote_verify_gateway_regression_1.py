from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from proof_agent.delivery import remote_verify_gateway
from proof_agent.delivery.remote_verify_gateway import GatewayConfig
from proof_agent.delivery.remote_verify_gateway import make_handler


# Regression for ISSUE-002 in the 2026-07-11 ProofAgent integration QA report.
CHAT_BASE = "/__proofagent_chat__/"


class HtmlResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attribute_name = "src" if tag == "script" else "href" if tag == "link" else None
        if attribute_name is None:
            return
        attributes = dict(attrs)
        path = attributes.get(attribute_name)
        if path is not None:
            self.paths.append(path)


@contextmanager
def upstream_server(label: str) -> Iterator[tuple[str, list[str]]]:
    requested_paths: list[str] = []

    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested_paths.append(self.path)
            parsed_path = urlsplit(self.path).path
            if label == "chat" and (
                parsed_path == f"{CHAT_BASE}operator"
                or parsed_path.startswith(f"{CHAT_BASE}operator/")
                or parsed_path == f"{CHAT_BASE}customer"
                or parsed_path.startswith(f"{CHAT_BASE}customer/")
            ):
                entry = parsed_path.removeprefix(CHAT_BASE)
                body = (
                    "<!doctype html>"
                    f'<script type="module" src="{CHAT_BASE}@vite/client?entry={entry}"></script>'
                    f'<script type="module" src="{CHAT_BASE}src/main.tsx?entry={entry}"></script>'
                ).encode("utf-8")
                content_type = "text/html"
            else:
                body = f"{label}:{self.path}".encode("utf-8")
                content_type = "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested_paths
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


@pytest.mark.parametrize(
    "public_entry",
    [
        "/operator",
        "/operator/c/conversation-1",
    ],
)
def test_chat_entry_and_emitted_vite_assets_stay_on_chat_upstream(
    public_entry: str,
) -> None:
    with (
        upstream_server("backend") as (backend_origin, _backend_paths),
        upstream_server("dashboard") as (dashboard_origin, dashboard_paths),
        upstream_server("chat") as (chat_origin, chat_paths),
    ):
        config = GatewayConfig(
            backend_origin=backend_origin,
            dashboard_origin=dashboard_origin,
            chat_origin=chat_origin,
            chat_base=CHAT_BASE,
        )
        with gateway_server(config) as gateway_origin:
            html = read_text(f"{gateway_origin}{public_entry}?qa=issue-002")

            expected_entry = f"{CHAT_BASE}{public_entry.lstrip('/')}?qa=issue-002"
            assert chat_paths == [expected_entry]

            parser = HtmlResourceParser()
            parser.feed(html)
            assert parser.paths == [
                f"{CHAT_BASE}@vite/client?entry={public_entry.lstrip('/')}",
                f"{CHAT_BASE}src/main.tsx?entry={public_entry.lstrip('/')}",
            ]
            for resource_path in parser.paths:
                assert read_text(f"{gateway_origin}{resource_path}") == (
                    f"chat:{resource_path}"
                )

            assert dashboard_paths == []


@pytest.mark.parametrize(
    "raw_base",
    ["__proofagent_chat__", "/__proofagent_chat__", "__proofagent_chat__/"],
)
def test_gateway_normalizes_chat_base(raw_base: str) -> None:
    config = GatewayConfig(
        backend_origin="http://127.0.0.1:8000/",
        dashboard_origin="http://127.0.0.1:5173/",
        chat_origin="http://127.0.0.1:5174/",
        chat_base=raw_base,
    )

    assert config.chat_base == CHAT_BASE


@pytest.mark.parametrize(
    ("extra_args", "expected_base"),
    [([], CHAT_BASE), (["--chat-base", "custom-chat"], "/custom-chat/")],
)
def test_gateway_main_threads_default_and_explicit_chat_base_into_config(
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    expected_base: str,
) -> None:
    captured_configs: list[GatewayConfig] = []
    captured_servers: list[tuple[tuple[str, int], type[BaseHTTPRequestHandler]]] = []

    def fake_make_handler(config: GatewayConfig) -> type[BaseHTTPRequestHandler]:
        captured_configs.append(config)
        return BaseHTTPRequestHandler

    class FakeServer:
        def __init__(
            self,
            address: tuple[str, int],
            handler: type[BaseHTTPRequestHandler],
        ) -> None:
            captured_servers.append((address, handler))

        def serve_forever(self) -> None:
            return

        def server_close(self) -> None:
            return

    monkeypatch.setattr(remote_verify_gateway, "make_handler", fake_make_handler)
    monkeypatch.setattr(remote_verify_gateway, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remote_verify_gateway",
            "--host",
            "127.0.0.1",
            "--port",
            "18080",
            "--backend-origin",
            "http://127.0.0.1:8000",
            "--dashboard-origin",
            "http://127.0.0.1:5173",
            "--chat-origin",
            "http://127.0.0.1:5174",
            *extra_args,
        ],
    )

    remote_verify_gateway.main()

    assert len(captured_configs) == 1
    assert captured_configs[0].chat_base == expected_base
    assert captured_servers == [(('127.0.0.1', 18080), BaseHTTPRequestHandler)]


def test_gateway_preserves_api_and_dashboard_query_strings() -> None:
    with (
        upstream_server("backend") as (backend_origin, _backend_paths),
        upstream_server("dashboard") as (dashboard_origin, _dashboard_paths),
        upstream_server("chat") as (chat_origin, _chat_paths),
        gateway_server(
            GatewayConfig(
                backend_origin=backend_origin,
                dashboard_origin=dashboard_origin,
                chat_origin=chat_origin,
            )
        ) as gateway_origin,
    ):
        assert read_text(f"{gateway_origin}/api?probe=health") == "backend:/api?probe=health"
        assert read_text(f"{gateway_origin}/runs/run-1?tab=evidence") == (
            "dashboard:/runs/run-1?tab=evidence"
        )


def test_gateway_handles_implicit_browser_favicon_without_asset_error() -> None:
    with (
        upstream_server("backend") as (backend_origin, backend_paths),
        upstream_server("dashboard") as (dashboard_origin, dashboard_paths),
        upstream_server("chat") as (chat_origin, chat_paths),
        gateway_server(
            GatewayConfig(
                backend_origin=backend_origin,
                dashboard_origin=dashboard_origin,
                chat_origin=chat_origin,
                chat_base=CHAT_BASE,
            )
        ) as gateway_origin,
    ):
        parsed_origin = urlsplit(gateway_origin)
        connection = HTTPConnection(parsed_origin.hostname, parsed_origin.port, timeout=5)
        try:
            connection.request("GET", "/favicon.ico")
            response = connection.getresponse()
            assert response.status == 204
            assert response.read() == b""
        finally:
            connection.close()

        assert backend_paths == []
        assert dashboard_paths == []
        assert chat_paths == []


def test_gateway_keeps_upgrade_rejection_for_issue_002() -> None:
    with (
        upstream_server("backend") as (backend_origin, _backend_paths),
        upstream_server("dashboard") as (dashboard_origin, _dashboard_paths),
        upstream_server("chat") as (chat_origin, _chat_paths),
        gateway_server(
            GatewayConfig(
                backend_origin=backend_origin,
                dashboard_origin=dashboard_origin,
                chat_origin=chat_origin,
            )
        ) as gateway_origin,
    ):
        parsed_origin = urlsplit(gateway_origin)
        connection = HTTPConnection(
            parsed_origin.hostname,
            parsed_origin.port,
            timeout=5,
        )
        try:
            connection.request(
                "GET",
                f"{CHAT_BASE}@vite/client",
                headers={"Connection": "Upgrade", "Upgrade": "websocket"},
            )
            response = connection.getresponse()
            response.read()
            assert response.status == 426
        finally:
            connection.close()
