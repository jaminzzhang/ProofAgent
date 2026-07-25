"""Hardened server for immutable Dashboard and Operator Chat build assets."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint


StaticSurface = Literal["dashboard", "operator-chat"]
_STATIC_BASE = Path("/opt/proofagent/static")
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def create_static_application(
    *,
    surface: StaticSurface,
    root: Path | None = None,
) -> FastAPI:
    """Create a no-listing SPA server bound to one verified asset directory."""

    if surface not in {"dashboard", "operator-chat"}:
        raise ValueError("static surface must be dashboard or operator-chat")
    asset_root = root or (_STATIC_BASE / surface)
    if asset_root.is_symlink():
        raise ValueError("static asset root cannot be a symlink")
    if not asset_root.is_dir():
        raise ValueError("static server requires a readable asset directory")
    asset_root = asset_root.resolve(strict=True)
    index_path = asset_root / "index.html"
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("static server requires a regular index.html")
    digest = _asset_tree_sha256(asset_root)

    application = FastAPI(
        title=f"Proof Agent {surface} static server",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @application.get("/.well-known/proof-agent-asset-digest", include_in_schema=False)
    def asset_digest() -> JSONResponse:
        return JSONResponse(
            content={"sha256": digest, "surface": surface},
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/{requested_path:path}", include_in_schema=False)
    def static_asset(requested_path: str) -> FileResponse:
        normalized = PurePosixPath(requested_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise HTTPException(status_code=404)
        candidate = asset_root.joinpath(*normalized.parts)
        if _is_regular_descendant(candidate, asset_root):
            cache_control = (
                "public, max-age=31536000, immutable"
                if normalized.parts and normalized.parts[0] == "assets"
                else "no-store"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache_control})
        if normalized.parts and (
            normalized.parts[0] == "assets" or normalized.suffix
        ):
            raise HTTPException(status_code=404)
        return FileResponse(index_path, headers={"Cache-Control": "no-store"})

    return application


def _asset_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("static asset directory cannot be empty")
    for path in files:
        if path.is_symlink():
            raise ValueError("static assets cannot contain symlinks")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _is_regular_descendant(path: Path, root: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


__all__ = ["StaticSurface", "create_static_application"]
