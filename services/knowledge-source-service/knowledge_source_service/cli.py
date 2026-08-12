"""Command-line interface shared by Knowledge Source Service process roles."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import os
import sys

from knowledge_source_service.configuration import (
    ApiRuntimeConfiguration,
    MissingRequiredConfiguration,
)


RoleRunner = Callable[[str, ApiRuntimeConfiguration, Mapping[str, str]], int]


PROCESS_ROLES = (
    "api",
    "query-executor",
    "knowledge-worker",
    "sync-scheduler",
    "migrate",
)


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    role_runner: RoleRunner | None = None,
) -> int:
    """Run one public service command and return a process exit status."""

    parser = argparse.ArgumentParser(prog="knowledge-source-service")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("roles", help="list stable process role names")
    for role in PROCESS_ROLES:
        role_parser = subparsers.add_parser(role, help=f"run the {role} process role")
        role_parser.add_argument("--check-config", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.command == "roles":
        print("\n".join(PROCESS_ROLES))
        return 0
    source = os.environ if environment is None else environment
    try:
        configuration = ApiRuntimeConfiguration.from_environment(source)
    except (MissingRequiredConfiguration, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if arguments.check_config:
        print("configuration valid")
        return 0
    if role_runner is None:
        from knowledge_source_service.bootstrap.processes import run_process_role

        role_runner = run_process_role
    return role_runner(arguments.command, configuration, source)


def console_main() -> int:
    """Installed umbrella console entry point."""

    return main()


def _selected_role_main(role: str) -> int:
    return main((role, *sys.argv[1:]))


def api_main() -> int:
    """Installed API role entry point."""

    return _selected_role_main("api")


def query_executor_main() -> int:
    """Installed Knowledge Query Executor role entry point."""

    return _selected_role_main("query-executor")


def knowledge_worker_main() -> int:
    """Installed ingestion worker role entry point."""

    return _selected_role_main("knowledge-worker")


def sync_scheduler_main() -> int:
    """Installed synchronization scheduler role entry point."""

    return _selected_role_main("sync-scheduler")


def migrate_main() -> int:
    """Installed database migration role entry point."""

    return _selected_role_main("migrate")
