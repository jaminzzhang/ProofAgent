from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import tomllib

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]


def _imports_module(path: Path, module_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == module_name or alias.name.startswith(f"{module_name}.")
                for alias in node.names
            ):
                return True
        if isinstance(node, ast.ImportFrom):
            imported = node.module or ""
            if imported == module_name or imported.startswith(f"{module_name}."):
                return True
    return False


def test_proof_agent_does_not_own_kss_implementation_or_distribution() -> None:
    assert not (ROOT / "knowledge_source_service").exists()
    assert not (ROOT / "services/knowledge-source-service").exists()
    assert not (ROOT / "deploy/production/knowledge").exists()


def test_proof_agent_python_does_not_import_kss_implementation() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for source_root in (ROOT / "proof_agent", ROOT / "tests", ROOT / "scripts")
        if source_root.exists()
        for path in source_root.rglob("*.py")
        if path != Path(__file__) and _imports_module(path, "knowledge_source_service")
    ]

    assert offenders == []


def test_production_local_consumes_one_external_kss_image_without_building_it() -> None:
    compose = yaml.safe_load(
        (ROOT / "docker-compose.production-local.yml").read_text(encoding="utf-8")
    )
    kss_role_names = (
        "kss-migrate",
        "kss-runtime-client-bootstrap",
        "kss-reference-client-bootstrap",
        "kss-api",
        "kss-query-executor",
        "kss-knowledge-worker",
        "kss-sync-scheduler",
    )
    kss_services = {name: compose["services"][name] for name in kss_role_names}

    assert kss_services
    assert all("build" not in service for service in kss_services.values())
    images = {service.get("image") for service in kss_services.values()}
    assert len(images) == 1
    assert next(iter(images)).startswith("${KSS_IMAGE:?")


def test_production_local_entry_requires_an_immutable_external_kss_image() -> None:
    script = (ROOT / "scripts/production-local-up.sh").read_text(encoding="utf-8")

    assert "KSS_IMAGE=${KSS_IMAGE:?" in script
    assert 'KSS_DIGEST=${KSS_IMAGE##*@sha256:}' in script
    assert '${#KSS_DIGEST}' in script
    assert "export KSS_IMAGE" in script


def test_production_local_entry_rejects_malformed_kss_image_before_prepare() -> None:
    script = ROOT / "scripts/production-local-up.sh"
    invalid_images = (
        "kss:latest",
        f"@sha256:{'0' * 64}",
        f"registry.example/kss@sha256:{'0' * 63}",
        f"registry.example/kss@sha256:{'A' * 64}",
    )

    for image in invalid_images:
        environment = os.environ.copy()
        environment["KSS_IMAGE"] = image
        result = subprocess.run(
            [str(script)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 2, (image, result.stderr)
        assert "KSS_IMAGE" in result.stderr


def test_proof_agent_image_does_not_request_removed_hybrid_extra() -> None:
    dockerfile = (ROOT / "Dockerfile.production").read_text(encoding="utf-8")

    assert ",hybrid" not in dockerfile
    for ignore_path in (
        ROOT / "deploy/production/.dockerignore",
        ROOT / "deploy/production/Dockerfile.dockerignore",
    ):
        assert "docker-compose.hybrid-test.yml" not in ignore_path.read_text(
            encoding="utf-8"
        )


def test_proof_agent_dependency_graph_excludes_kss_only_format_parsers() -> None:
    with (ROOT / "pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)
    project = configuration["project"]
    declared = {
        dependency.split("[", 1)[0].split("<", 1)[0].split(">", 1)[0].lower()
        for group in (project["dependencies"], *project["optional-dependencies"].values())
        for dependency in group
    }

    assert {"openpyxl", "pillow", "pyarrow"}.isdisjoint(declared)
