"""Tests for runs/latest symlink backward compatibility."""

from pathlib import Path

from proof_agent.observability.storage.compat import update_latest_symlink


def test_creates_symlink(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    run_dir = history / "run_abc123"
    run_dir.mkdir()

    update_latest_symlink(run_dir, tmp_path)

    latest = tmp_path / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == run_dir


def test_updates_existing_symlink(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    first = history / "run_001"
    first.mkdir()
    second = history / "run_002"
    second.mkdir()

    update_latest_symlink(first, tmp_path)
    assert (tmp_path / "latest").resolve() == first

    update_latest_symlink(second, tmp_path)
    assert (tmp_path / "latest").resolve() == second


def test_noop_when_latest_is_real_directory(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    run_dir = history / "run_abc123"
    run_dir.mkdir()

    latest = tmp_path / "latest"
    latest.mkdir()

    update_latest_symlink(run_dir, tmp_path)
    assert latest.is_dir() and not latest.is_symlink()
