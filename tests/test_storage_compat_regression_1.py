"""Regression coverage for atomic ``runs/latest`` compatibility links."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from proof_agent.observability.storage.compat import update_latest_symlink


def test_repository_relative_run_dir_resolves_from_latest_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = Path("runs/history/run_relative")
    run_dir.mkdir(parents=True)

    update_latest_symlink(run_dir, Path("runs"))

    latest = Path("runs/latest")
    assert latest.is_symlink()
    assert latest.readlink() == Path("history/run_relative")
    assert latest.resolve() == run_dir.resolve()


def test_semantic_run_and_runs_root_paths_survive_lexical_alias_removal(
    tmp_path: Path,
) -> None:
    actual_runs = tmp_path / "actual/runs"
    run_dir = actual_runs / "history/run_semantic"
    run_dir.mkdir(parents=True)
    runs_root_alias = tmp_path / "runs"
    runs_root_alias.symlink_to(actual_runs, target_is_directory=True)
    run_dir_alias = tmp_path / "run-alias"
    run_dir_alias.symlink_to(run_dir, target_is_directory=True)

    update_latest_symlink(run_dir_alias, runs_root_alias)
    run_dir_alias.unlink()

    latest = runs_root_alias / "latest"
    assert latest.readlink() == Path("history/run_semantic")
    assert latest.exists()
    assert latest.resolve() == run_dir.resolve()


def test_broken_latest_symlink_is_repaired_for_relative_run_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = Path("runs/history/run_repaired")
    run_dir.mkdir(parents=True)
    latest = Path("runs/latest")
    latest.symlink_to("history/run_missing", target_is_directory=True)
    assert latest.is_symlink() and not latest.exists()

    update_latest_symlink(run_dir, Path("runs"))

    assert latest.is_symlink()
    assert latest.exists()
    assert latest.resolve() == run_dir.resolve()


def test_replace_failure_cleans_unique_sibling_links_and_preserves_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    history = runs_root / "history"
    old_run = history / "run_old"
    new_run = history / "run_new"
    old_run.mkdir(parents=True)
    new_run.mkdir()
    latest = runs_root / "latest"
    latest.symlink_to(Path("history/run_old"), target_is_directory=True)
    replace_sources: list[Path] = []

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == latest.parent
        assert source_path != latest
        assert source_path.is_symlink()
        assert destination_path == latest
        replace_sources.append(source_path)
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    update_latest_symlink(new_run, runs_root)
    update_latest_symlink(new_run, runs_root)

    assert len(replace_sources) == 2
    assert replace_sources[0] != replace_sources[1]
    assert latest.is_symlink()
    assert latest.resolve() == old_run.resolve()
    assert set(runs_root.iterdir()) == {history, latest}


@pytest.mark.parametrize("node_kind", ["directory", "file"])
def test_real_latest_node_is_preserved_without_attempting_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node_kind: str,
) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "history/run_new"
    run_dir.mkdir(parents=True)
    latest = runs_root / "latest"
    if node_kind == "directory":
        latest.mkdir()
        marker = latest / "keep.txt"
    else:
        marker = latest
    marker.write_text("keep", encoding="utf-8")
    replace_calls: list[tuple[Path, Path]] = []

    def unexpected_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        replace_calls.append((Path(source), Path(destination)))
        raise OSError("real latest nodes must be rejected before replace")

    monkeypatch.setattr(os, "replace", unexpected_replace)

    update_latest_symlink(run_dir, runs_root)

    assert replace_calls == []
    assert not latest.is_symlink()
    assert latest.is_dir() is (node_kind == "directory")
    assert latest.is_file() is (node_kind == "file")
    assert marker.read_text(encoding="utf-8") == "keep"
    assert set(runs_root.iterdir()) == {runs_root / "history", latest}
