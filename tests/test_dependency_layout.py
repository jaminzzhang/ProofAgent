import tomllib
from pathlib import Path


def test_vector_stack_is_optional_not_core_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    optional = pyproject["project"]["optional-dependencies"]

    assert not any(dependency.startswith("chromadb") for dependency in dependencies)
    assert not any(dependency.startswith("sentence-transformers") for dependency in dependencies)
    assert any(dependency.startswith("chromadb") for dependency in optional["vector"])
    assert any(dependency.startswith("sentence-transformers") for dependency in optional["vector"])
