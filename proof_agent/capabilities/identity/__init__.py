"""Backend OIDC client adapters."""

from proof_agent.capabilities.identity.oidc_client import (
    GuardedOidcClient,
    OidcProviderConfiguration,
)

__all__ = ["GuardedOidcClient", "OidcProviderConfiguration"]
