from __future__ import annotations

from collections.abc import Iterator
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
import httpx


SERVICE_PROJECT = Path(__file__).resolve().parents[3] / "services/knowledge-source-service"
sys.path.insert(0, str(SERVICE_PROJECT))


@pytest.fixture
def kss_postgres_dsn() -> Iterator[str]:
    base_dsn = (
        os.environ.get("KSS_TEST_POSTGRES_DSN", "").strip()
        or os.environ.get("PROOF_AGENT_TEST_POSTGRES_DSN", "").strip()
    )
    require_database = (
        os.environ.get("KSS_REQUIRE_POSTGRES_TESTS") == "1"
        or os.environ.get("PROOF_AGENT_REQUIRE_POSTGRES_TESTS") == "1"
    )
    if not base_dsn:
        if require_database:
            pytest.fail("KSS_TEST_POSTGRES_DSN is required for PostgreSQL tests")
        pytest.skip("real Knowledge service PostgreSQL DSN is not configured")

    psycopg_dsn = base_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    schema = f"kss_test_{uuid4().hex}"
    with psycopg.connect(psycopg_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parameters = conninfo_to_dict(psycopg_dsn)
    existing_options = parameters.get("options", "")
    parameters["options"] = f"{existing_options} -csearch_path={schema}".strip()
    isolated_dsn = make_conninfo(**parameters)
    try:
        yield isolated_dsn
    finally:
        with psycopg.connect(psycopg_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def kss_s3_bucket() -> Iterator[tuple[Any, str]]:
    endpoint = os.environ.get("KSS_TEST_S3_ENDPOINT", "").strip()
    require_store = os.environ.get("KSS_REQUIRE_S3_TESTS") == "1"
    if not endpoint:
        if require_store:
            pytest.fail("KSS_TEST_S3_ENDPOINT is required for S3 tests")
        pytest.skip("real Knowledge service S3 endpoint is not configured")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("KSS_TEST_S3_ACCESS_KEY", "proof"),
        aws_secret_access_key=os.environ.get(
            "KSS_TEST_S3_SECRET_KEY", "proof-test-secret"
        ),
        region_name="us-east-1",
        config=Config(
            connect_timeout=2,
            read_timeout=2,
            retries={"max_attempts": 0},
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )
    bucket = f"kss-test-{uuid4().hex}"
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )
    try:
        yield client, bucket
    finally:
        versions = client.list_object_versions(Bucket=bucket)
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for collection in (
                versions.get("Versions", []),
                versions.get("DeleteMarkers", []),
            )
            for item in collection
        ]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        client.delete_bucket(Bucket=bucket)
        client.close()


@pytest.fixture
def kss_search_endpoint() -> str:
    endpoint = os.environ.get("KSS_TEST_SEARCH_ENDPOINT", "").strip()
    require_search = os.environ.get("KSS_REQUIRE_SEARCH_TESTS") == "1"
    if not endpoint:
        if require_search:
            pytest.fail("KSS_TEST_SEARCH_ENDPOINT is required for search tests")
        pytest.skip("real Knowledge service search endpoint is not configured")
    with httpx.Client(timeout=3, trust_env=False) as client:
        response = client.get(f"{endpoint.rstrip('/')}/_cluster/health")
        response.raise_for_status()
    return endpoint.rstrip("/")
