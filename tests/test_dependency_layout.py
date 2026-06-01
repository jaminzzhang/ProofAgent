import tomllib
from pathlib import Path


def test_local_index_stack_is_optional_not_core_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    optional = pyproject["project"]["optional-dependencies"]

    assert not any(dependency.startswith("llama-index-core") for dependency in dependencies)
    assert "vector" not in optional
    assert any(dependency.startswith("llama-index-core") for dependency in optional["tree"])
