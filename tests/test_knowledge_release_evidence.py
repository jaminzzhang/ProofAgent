from __future__ import annotations

from pathlib import Path

from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
)
from proof_agent.configuration.knowledge_release_evidence import (
    upload_knowledge_release_evidence,
)


def test_upload_release_evidence_returns_four_distinct_exact_refs(tmp_path: Path) -> None:
    paths = {}
    for kind in ("shadow", "capacity", "acceptance", "recovery"):
        path = tmp_path / f"{kind}.json"
        path.write_text(f'{{"kind":"{kind}","passed":true}}', encoding="utf-8")
        paths[kind] = path
    with FileSystemKnowledgeArtifactStore(tmp_path / "artifacts") as artifacts:
        evidence = upload_knowledge_release_evidence(
            artifact_store=artifacts,
            **paths,
        )
        refs = (
            evidence.shadow,
            evidence.capacity,
            evidence.acceptance,
            evidence.recovery,
        )
        assert len({ref.sha256 for ref in refs}) == 4
        assert all(artifacts.get_exact(ref) for ref in refs)
