from pathlib import Path

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore


def publish_agent_package(
    root_dir: Path,
    manifest_path: Path,
    *,
    actor: str = "test-user",
    validation_run_id: str = "run_validation",
) -> LocalAgentConfigurationStore:
    store = LocalAgentConfigurationStore(root_dir / "config")
    draft = import_agent_package(manifest_path, store=store, actor=actor)
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id=validation_run_id,
        actor=actor,
    )
    return store
