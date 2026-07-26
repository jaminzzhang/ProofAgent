from __future__ import annotations

from datetime import UTC, datetime
import base64
import json

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.model_credential_repository import (
    PostgresModelCredentialRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    model_connection_credentials,
    model_connections,
)
from proof_agent.bootstrap.model_credentials import compose_model_credential_cipher
from proof_agent.control.security.envelope_cipher import (
    EnvelopeCipher,
    EnvelopeUnavailableError,
)
from proof_agent.contracts.ports.model_credentials import ModelCredentialResolutionError


pytest_plugins = ("postgres_fixtures",)

KEY_V1 = b"1" * 32
KEY_V2 = b"2" * 32


def _seed_model_connection(postgres_engine: Engine) -> None:
    created_at = datetime(2026, 7, 26, tzinfo=UTC)
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.insert(model_connections).values(
                connection_id="model_primary",
                revision=1,
                lifecycle_state="ACTIVE",
                configuration_json={},
                created_at=created_at,
                updated_at=created_at,
            )
        )


def test_envelope_cipher_binds_ciphertext_to_connection_context_and_key_version() -> None:
    cipher = EnvelopeCipher(active_key_version="v2", keys={"v1": KEY_V1, "v2": KEY_V2})

    envelope = cipher.encrypt(b"sk-provider-secret", context="model-credential:model_primary")

    assert envelope.key_version == "v2"
    assert b"sk-provider-secret" not in envelope.ciphertext
    assert cipher.decrypt(
        envelope.ciphertext,
        key_version=envelope.key_version,
        context="model-credential:model_primary",
    ) == b"sk-provider-secret"
    with pytest.raises(EnvelopeUnavailableError):
        cipher.decrypt(
            envelope.ciphertext,
            key_version=envelope.key_version,
            context="model-credential:model_other",
        )


def test_model_credential_keyring_file_loads_versioned_base64_keys(tmp_path) -> None:
    keyring_path = tmp_path / "model-credential-keyring.json"
    keyring_path.write_text(
        json.dumps(
            {
                "active_key_version": "v2",
                "keys": {
                    "v1": base64.b64encode(KEY_V1).decode("ascii"),
                    "v2": base64.b64encode(KEY_V2).decode("ascii"),
                },
            }
        ),
        encoding="utf-8",
    )

    cipher = compose_model_credential_cipher(
        {"PROOF_AGENT_MODEL_CREDENTIAL_KEYRING_FILE": str(keyring_path)}
    )

    assert cipher.active_key_version == "v2"
    envelope = cipher.encrypt(b"secret", context="model-credential:model_primary")
    assert cipher.decrypt(
        envelope.ciphertext,
        key_version="v2",
        context="model-credential:model_primary",
    ) == b"secret"


def test_keyring_rotation_reads_old_envelopes_and_writes_the_active_version() -> None:
    original = EnvelopeCipher(active_key_version="v1", keys={"v1": KEY_V1})
    old_envelope = original.encrypt(
        b"secret",
        context="model-credential:model_primary",
    )
    rotated = EnvelopeCipher(
        active_key_version="v2",
        keys={"v1": KEY_V1, "v2": KEY_V2},
    )

    assert rotated.decrypt(
        old_envelope.ciphertext,
        key_version=old_envelope.key_version,
        context="model-credential:model_primary",
    ) == b"secret"
    assert rotated.encrypt(
        b"secret",
        context="model-credential:model_primary",
    ).key_version == "v2"


def test_model_credential_keyring_has_no_environment_value_fallback() -> None:
    with pytest.raises(ValueError, match="KEYRING_FILE is required"):
        compose_model_credential_cipher({})


@pytest.mark.postgres_integration
def test_postgres_model_credential_repository_persists_only_authenticated_ciphertext(
    postgres_engine: Engine,
) -> None:
    _seed_model_connection(postgres_engine)
    repository = PostgresModelCredentialRepository(
        postgres_engine,
        cipher=EnvelopeCipher(active_key_version="v1", keys={"v1": KEY_V1}),
    )
    checked_at = datetime(2026, 7, 26, tzinfo=UTC)

    repository.store(
        "model_primary",
        b"sk-provider-secret",
        updated_at=checked_at,
    )

    with postgres_engine.connect() as connection:
        row = connection.execute(
            sa.select(
                model_connection_credentials.c.key_version,
                model_connection_credentials.c.ciphertext,
            ).where(model_connection_credentials.c.connection_id == "model_primary")
        ).mappings().one()
    assert row["key_version"] == "v1"
    assert b"sk-provider-secret" not in bytes(row["ciphertext"])
    assert repository.resolve("model_primary").reveal_for_use() == b"sk-provider-secret"
    assert repository.validate("model_primary").resolvable is True


@pytest.mark.postgres_integration
def test_postgres_model_credential_repository_fails_closed_with_wrong_key(
    postgres_engine: Engine,
) -> None:
    _seed_model_connection(postgres_engine)
    writer = PostgresModelCredentialRepository(
        postgres_engine,
        cipher=EnvelopeCipher(active_key_version="v1", keys={"v1": KEY_V1}),
    )
    writer.store(
        "model_primary",
        b"sk-provider-secret",
        updated_at=datetime(2026, 7, 26, tzinfo=UTC),
    )
    reader = PostgresModelCredentialRepository(
        postgres_engine,
        cipher=EnvelopeCipher(active_key_version="v1", keys={"v1": KEY_V2}),
    )

    assert reader.validate("model_primary").resolvable is False
    with pytest.raises(
        ModelCredentialResolutionError,
        match="model credential cannot be resolved",
    ):
        reader.resolve("model_primary")
