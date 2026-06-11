import ast
import tomllib
from pathlib import Path


def test_local_index_stack_is_optional_not_core_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    optional = pyproject["project"]["optional-dependencies"]

    assert not any(dependency.startswith("llama-index-core") for dependency in dependencies)
    assert "vector" not in optional
    assert any(dependency.startswith("llama-index-core") for dependency in optional["tree"])


def test_langgraph_runtime_is_the_only_workflow_execution_entrypoint() -> None:
    assert not Path("proof_agent/control/workflow/orchestrator.py").exists()


def test_react_graph_builder_does_not_own_workflow_node_implementations() -> None:
    tree = ast.parse(Path("proof_agent/runtime/react_graph.py").read_text(encoding="utf-8"))
    builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_react_enterprise_qa_graph"
    )

    nested_node_functions = [
        node.name
        for node in ast.walk(builder)
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_node")
    ]

    assert nested_node_functions == []
