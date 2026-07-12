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


def test_v3_delivery_has_no_legacy_runtime_entrypoint() -> None:
    package_execution = Path("proof_agent/delivery/agent_package_execution.py")
    imported_modules = {
        imported_module
        for node in ast.walk(ast.parse(package_execution.read_text(encoding="utf-8")))
        for imported_module in _resolved_import_modules(package_execution, node)
    }
    assert not {
        imported_module
        for imported_module in imported_modules
        if imported_module.startswith(("proof_agent.runtime", "langgraph", "langchain"))
    }

    run_service_imports = _imports_by_module(Path("proof_agent/delivery/run_execution_service.py"))
    assert "LangGraphApprovalResumeContext" not in run_service_imports.get(
        "proof_agent.runtime.approval_resume", set()
    )


def test_react_graph_builder_does_not_own_workflow_node_implementations() -> None:
    tree = ast.parse(Path("proof_agent/runtime/react_graph.py").read_text(encoding="utf-8"))
    builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_react_enterprise_qa_graph"
    )

    nested_node_functions = [
        node.name
        for node in ast.walk(builder)
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_node")
    ]

    assert nested_node_functions == []


def test_controlled_react_leaf_modules_do_not_import_legacy_or_runtime_frameworks() -> None:
    banned_prefixes = (
        "proof_agent.control.workflow.react_enterprise_qa",
        "proof_agent.runtime",
        "langgraph",
        "langchain",
    )
    violations: list[str] = []

    controlled_react_root = Path("proof_agent/control/workflow/controlled_react")
    for module_path in sorted(controlled_react_root.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_modules = _resolved_import_modules(module_path, node)
            for imported_module in imported_modules:
                if imported_module.startswith(banned_prefixes):
                    violations.append(f"{module_path}:{node.lineno}: {imported_module}")

    assert violations == []


def test_v3_delivery_imports_execution_input_from_controlled_react() -> None:
    tree = ast.parse(
        Path("proof_agent/delivery/agent_package_execution.py").read_text(encoding="utf-8")
    )
    imports_by_module = {
        node.module: {alias.name for alias in node.names}
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "proof_agent.control.workflow.controlled_react.execution_input" in imports_by_module
    assert {
        "resolve_workflow_stage_runtime_configuration",
        "build_workflow_template_execution_input",
    } <= imports_by_module["proof_agent.control.workflow.controlled_react.execution_input"]
    assert not {
        "_resolve_workflow_stage_runtime_configuration",
        "_workflow_template_execution_input",
    } & imports_by_module.get("proof_agent.runtime.langgraph_runner", set())


def test_runtime_adapters_delegate_v3_authorities_to_controlled_react() -> None:
    langgraph_imports = _imports_by_module(Path("proof_agent/runtime/langgraph_runner.py"))
    approval_imports = _imports_by_module(Path("proof_agent/runtime/approval_resume.py"))

    assert {
        "build_workflow_template_execution_input",
        "resolve_workflow_stage_runtime_configuration",
    } <= langgraph_imports["proof_agent.control.workflow.controlled_react.execution_input"]
    assert {
        "FileControlledReActSnapshotStore",
        "FileObservationTruthStore",
    } <= approval_imports["proof_agent.control.workflow.controlled_react.local_stores"]


def test_controlled_react_consumers_use_focused_leaf_authorities() -> None:
    orchestrator_imports = _imports_by_module(
        Path("proof_agent/control/workflow/controlled_react/orchestrator.py")
    )
    composition_imports = _imports_by_module(
        Path("proof_agent/control/workflow/controlled_react/composition.py")
    )
    final_answer_imports = _imports_by_module(
        Path("proof_agent/control/workflow/controlled_react/final_answer_attempt.py")
    )

    assert "proof_agent.control.workflow.controlled_react.action_control" in (orchestrator_imports)
    assert "proof_agent.control.workflow.controlled_react.review" in composition_imports
    assert "proof_agent.control.workflow.controlled_react.model_tracing" in composition_imports
    assert "proof_agent.control.workflow.controlled_react.model_tracing" in final_answer_imports


def test_import_from_candidates_include_parent_and_qualified_aliases() -> None:
    path = Path("proof_agent/control/workflow/controlled_react/example.py")
    runtime_import = ast.parse("from proof_agent import runtime").body[0]
    legacy_import = ast.parse("from proof_agent.control.workflow import react_enterprise_qa").body[
        0
    ]

    assert _resolved_import_modules(path, runtime_import) == (
        "proof_agent",
        "proof_agent.runtime",
    )
    assert _resolved_import_modules(path, legacy_import) == (
        "proof_agent.control.workflow",
        "proof_agent.control.workflow.react_enterprise_qa",
    )


def _imports_by_module(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return imports


def _resolved_import_modules(path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    if node.level == 0:
        if node.module is None:
            return ()
        return _import_from_candidates(node.module, node)

    package_parts = list(path.with_suffix("").parts[:-1])
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return ("<invalid-relative-import>",)
    resolved_parent = package_parts[: len(package_parts) - parent_count]
    if node.module is not None:
        module = ".".join((*resolved_parent, *node.module.split(".")))
        return _import_from_candidates(module, node)
    module = ".".join(resolved_parent)
    return _import_from_candidates(module, node)


def _import_from_candidates(module: str, node: ast.ImportFrom) -> tuple[str, ...]:
    candidates = [module]
    candidates.extend(f"{module}.{alias.name}" for alias in node.names if alias.name != "*")
    return tuple(dict.fromkeys(candidates))
