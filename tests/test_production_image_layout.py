from __future__ import annotations

import json
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _numeric_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_production_dockerfile_builds_distributions_and_runs_non_root() -> None:
    dockerfile = PROJECT_ROOT / "deploy/production/Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "ARG NODE_IMAGE" in content
    assert "ARG UV_IMAGE" in content
    assert "ARG RUNTIME_IMAGE" in content
    assert "npm ci" in content
    assert "uv build" in content
    assert '".[dev]"' not in content
    assert "pip install -e" not in content
    assert "COPY . ." not in content
    assert "USER 10001:10001" in content
    assert 'CMD ["proof-agent", "server"' in content
    assert 'CMD ["proof-agent", "demo"]' not in content
    assert "/opt/proofagent/static/dashboard" in content
    assert "/opt/proofagent/static/operator-chat" in content


def test_production_image_installs_the_frozen_non_editable_environment() -> None:
    dockerfile = PROJECT_ROOT / "deploy/production/Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "UV_PROJECT_ENVIRONMENT=/opt/proofagent/venv" in content
    assert "uv sync --frozen --no-dev --no-editable --extra production" in content
    assert "uv pip install" not in content


def test_frontend_build_lock_excludes_known_high_severity_versions() -> None:
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    locked_packages = package_lock["packages"]

    assert _numeric_version(package["overrides"]["nanoid"]) >= (3, 3, 18)
    assert _numeric_version(package["overrides"]["postcss"]) >= (8, 5, 23)
    assert _numeric_version(locked_packages["node_modules/nanoid"]["version"]) >= (
        3,
        3,
        18,
    )
    assert _numeric_version(locked_packages["node_modules/postcss"]["version"]) >= (
        8,
        5,
        23,
    )
    assert _numeric_version(
        locked_packages["node_modules/react-router"]["version"]
    ) >= (7, 18, 2)


def test_production_docker_context_excludes_local_and_sensitive_content() -> None:
    ignore = (
        PROJECT_ROOT / "deploy/production/Dockerfile.dockerignore"
    ).read_text(encoding="utf-8")

    for excluded in (
        ".git",
        ".env",
        "tests",
        "runs",
        "reports",
        "graphify-out",
        "dashboard/dist",
        "chat/dist",
    ):
        assert excluded in ignore


def test_production_extra_contains_runtime_but_not_mcp_or_dev_tooling() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    production = "\n".join(extras["production"]).casefold()
    development = "\n".join(extras["dev"]).casefold()

    for required in ("fastapi", "uvicorn", "boto3", "sqlalchemy", "openai"):
        assert required in production
    for prohibited in ("pytest", "ruff", "mypy", "mcp"):
        assert prohibited not in production
    assert "mcp[cli]" in development


def test_root_dockerfile_remains_explicitly_development_only() -> None:
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'LABEL org.opencontainers.image.title="Proof Agent development image"' in content
    assert 'LABEL org.opencontainers.image.production="false"' in content
