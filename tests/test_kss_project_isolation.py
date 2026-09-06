from __future__ import annotations

import ast
from pathlib import Path
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


def test_default_topology_has_no_kss_image_services_or_environment() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.production-local.yml").read_text())
    assert not any("kss" in name for name in compose["services"])
    assert "KSS_IMAGE" not in str(compose)
    assert "PROOF_AGENT_KSS_" not in str(compose)
    for service in compose["services"].values():
        assert isinstance(service.get("environment", {}), dict)
        assert set(service.get("depends_on", {})).issubset(compose["services"])


def test_local_entry_never_requires_or_resolves_a_kss_image() -> None:
    script = (ROOT / "scripts/production-local-up.sh").read_text()
    assert "KSS" not in script
    assert '"$ROOT_DIR/scripts/production-local-prepare.sh"' in script
    assert 'config --quiet' in script


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
