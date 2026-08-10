from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proof_agent.delivery.static_server import create_static_application
from proof_agent.observability.api.app import create_app


def _assets(tmp_path: Path) -> Path:
    root = tmp_path / "dashboard"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (root / "assets" / "index-a1b2c3.js").write_text(
        "console.log('safe')",
        encoding="utf-8",
    )
    return root


def test_static_server_serves_spa_assets_with_security_and_cache_headers(
    tmp_path: Path,
) -> None:
    root = _assets(tmp_path)
    client = TestClient(create_static_application(surface="dashboard", root=root))

    index = client.get("/runs/019f")
    asset = client.get("/assets/index-a1b2c3.js")

    assert index.status_code == 200
    assert index.text == "<html>dashboard</html>"
    assert index.headers["cache-control"] == "no-store"
    assert index.headers["content-security-policy"] == "default-src 'self'"
    assert index.headers["x-content-type-options"] == "nosniff"
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_static_server_has_no_directory_listing_or_asset_spa_fallback(tmp_path: Path) -> None:
    root = _assets(tmp_path)
    client = TestClient(create_static_application(surface="dashboard", root=root))

    assert client.get("/assets/").status_code == 404
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/../pyproject.toml").status_code == 404


def test_static_server_exposes_digest_of_exact_asset_tree(tmp_path: Path) -> None:
    root = _assets(tmp_path)
    client = TestClient(create_static_application(surface="dashboard", root=root))

    first = client.get("/.well-known/proof-agent-asset-digest").json()
    (root / "assets" / "index-a1b2c3.js").write_text("changed", encoding="utf-8")
    changed_client = TestClient(
        create_static_application(surface="dashboard", root=root)
    )
    second = changed_client.get("/.well-known/proof-agent-asset-digest").json()

    assert first["surface"] == "dashboard"
    assert len(first["sha256"]) == hashlib.sha256().digest_size * 2
    assert first["sha256"] != second["sha256"]


def test_static_server_rejects_missing_or_symlinked_asset_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="readable asset directory"):
        create_static_application(surface="dashboard", root=tmp_path / "missing")

    real = _assets(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="cannot be a symlink"):
        create_static_application(surface="operator-chat", root=linked)


def test_combined_api_serves_dashboard_deep_links_without_masking_api_404(
    tmp_path: Path,
) -> None:
    root = _assets(tmp_path)
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            evaluations_dir=tmp_path / "evaluations",
            evaluation_campaigns_dir=tmp_path / "campaigns",
            evaluation_curation_dir=tmp_path / "curation",
            runs_dir=tmp_path / "runs",
            conversations_dir=tmp_path / "conversations",
            published_agents={},
            static_dir=root,
            agent_configuration_dir=tmp_path / "configuration",
        )
    )

    deep_link = client.get(
        "/knowledge/ks_insurance",
        headers={"Accept": "text/html"},
    )
    missing_api = client.get("/api/does-not-exist")

    assert deep_link.status_code == 200
    assert deep_link.text == "<html>dashboard</html>"
    assert deep_link.headers["cache-control"] == "no-store"
    assert missing_api.status_code == 404
    assert missing_api.headers["content-type"].startswith("application/json")
    assert missing_api.json() == {"detail": "Not Found"}
