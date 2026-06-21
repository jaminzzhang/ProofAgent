from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP


def build_server(*, host: str, port: int) -> FastMCP:
    mcp = FastMCP(
        "Proof Agent Claims MCP",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
    )

    @mcp.tool(name="claim.status.lookup", description="Lookup claim status")
    def claim_status_lookup(claim_id: str) -> dict[str, str]:
        return {"claim_id": claim_id, "status": "open"}

    @mcp.tool(
        name="claim.status.lookup_broken",
        description="Return a deliberately invalid status shape",
    )
    def claim_status_lookup_broken(claim_id: str) -> dict[str, object]:
        return {"claim_id": claim_id, "status": 7}

    @mcp.tool(name="ticket.create", description="Create a deterministic service ticket")
    def ticket_create(
        subject: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        return {
            "ticket_id": f"TCK-{customer_id[-3:]}",
            "status": "created",
            "idempotency_key_echo": idempotency_key,
            "subject": subject,
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic fake Claims MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    build_server(host=args.host, port=args.port).run(args.transport)


if __name__ == "__main__":
    main()
