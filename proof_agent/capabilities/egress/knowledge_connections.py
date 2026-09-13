"""Development-only DNS-class policy behind the existing pinned HTTPS client."""

from collections.abc import Callable
import ipaddress
from urllib.parse import urlsplit

from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient, SystemAddressResolver
from proof_agent.contracts.egress import EgressPolicyVersion, ExactHttpsOrigin
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.knowledge_connection import KnowledgeConnectionAuthorization
from proof_agent.control.security.egress import (
    AdmittedEgressHop,
    CompiledEgressPolicy,
    EgressDeniedError,
)


_PROXY_HOSTS = frozenset({"api.agentset.ai", "api.dify.ai"})
_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_TRANSLATED_IPV4 = ipaddress.ip_network("::ffff:0:0:0/96")


def binding_origin(binding: ExternalKnowledgeBinding) -> ExactHttpsOrigin:
    parsed = urlsplit(binding.endpoint)
    # The strict binding contract has already rejected userinfo/query/fragment.
    return ExactHttpsOrigin.parse(f"https://{parsed.netloc}")


class DevelopmentKnowledgePolicy(CompiledEgressPolicy):
    def __init__(
        self, lookup: Callable[[ExactHttpsOrigin], KnowledgeConnectionAuthorization | None]
    ):
        super().__init__(
            EgressPolicyVersion(
                version_id="development-knowledge-connections-v1",
                revision=1,
                created_at="server-owned",
                created_by="server-owned",
            )
        )
        self._lookup = lookup

    def authorize_origin(self, url: str) -> ExactHttpsOrigin:
        parsed = urlsplit(url)
        if parsed.fragment:
            raise EgressDeniedError(reason_code="fragment_forbidden")
        try:
            origin = ExactHttpsOrigin.parse(f"{parsed.scheme}://{parsed.netloc}")
        except ValueError:
            raise EgressDeniedError(reason_code="origin_not_allowed") from None
        if self._lookup(origin) is None:
            raise EgressDeniedError(reason_code="origin_not_allowed")
        return origin

    def admit(self, url: str, *, resolved_addresses: tuple[str, ...]) -> AdmittedEgressHop:
        origin = self.authorize_origin(url)
        grant = self._lookup(origin)
        if grant is None:
            raise EgressDeniedError(reason_code="origin_not_allowed")
        if not resolved_addresses or len(resolved_addresses) > 16:
            raise EgressDeniedError(reason_code="dns_answer_limit")
        normalized = []
        for value in resolved_addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                raise EgressDeniedError(reason_code="dns_address_invalid") from None
            effective = (
                address.ipv4_mapped
                if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped
                else address
            )
            if isinstance(address, ipaddress.IPv6Address) and address in _TRANSLATED_IPV4:
                effective = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
            proxy = (
                grant.address_mode == "local_proxy_dns"
                and origin.host in _PROXY_HOSTS
                and origin.port == 443
                and effective.version == 4
                and effective in _PROXY_NETWORK
            )
            # Exclude transition mechanisms that can encode a non-public IPv4 destination.
            transition = isinstance(effective, ipaddress.IPv6Address) and (
                effective.sixtofour is not None
                or effective.teredo is not None
                or effective in ipaddress.ip_network("64:ff9b::/96")
                or effective in ipaddress.ip_network("64:ff9b:1::/48")
            )
            if not proxy and (not effective.is_global or effective.is_multicast or transition):
                raise EgressDeniedError(reason_code="dns_address_not_allowed")
            normalized.append(str(address))
        return AdmittedEgressHop(origin=origin, addresses=tuple(sorted(set(normalized))))


def verify_authorization_dns(grant: KnowledgeConnectionAuthorization) -> None:
    policy = DevelopmentKnowledgePolicy(lambda origin: grant if origin == grant.origin else None)
    try:
        answers = SystemAddressResolver().resolve(
            grant.origin.host, grant.origin.port, timeout_seconds=5
        )
    except OSError:
        raise EgressDeniedError(reason_code="dns_resolution_failed") from None
    policy.admit(grant.origin.value, resolved_addresses=answers)


def knowledge_connection_client(
    lookup: Callable[[ExactHttpsOrigin], KnowledgeConnectionAuthorization | None],
) -> GuardedHttpsClient:
    return GuardedHttpsClient(
        policy=DevelopmentKnowledgePolicy(lookup), max_redirects=0, max_response_bytes=1024 * 1024
    )
