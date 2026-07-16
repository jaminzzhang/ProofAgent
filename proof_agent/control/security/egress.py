from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit

from proof_agent.contracts.egress import EgressOriginRule, EgressPolicyVersion, ExactHttpsOrigin


class EgressDeniedError(RuntimeError):
    def __init__(self, *, reason_code: str, origin: str | None = None) -> None:
        self.reason_code = reason_code
        self.origin = origin
        message = f"production egress denied: {reason_code}"
        if origin is not None:
            message += f" ({origin})"
        super().__init__(message)


@dataclass(frozen=True)
class AdmittedEgressHop:
    origin: ExactHttpsOrigin
    addresses: tuple[str, ...]


class CompiledEgressPolicy:
    """Exact-origin and all-address DNS admission for every outbound hop."""

    def __init__(self, version: EgressPolicyVersion) -> None:
        self.version = version
        self._rules = {
            (rule.origin.host, rule.origin.port): _CompiledOriginRule.from_contract(rule)
            for rule in version.rules
        }

    def authorize_origin(self, url: str) -> ExactHttpsOrigin:
        origin = _origin_from_url(url)
        if (origin.host, origin.port) not in self._rules:
            raise EgressDeniedError(reason_code="origin_not_allowed", origin=origin.value)
        return origin

    def admit(self, url: str, *, resolved_addresses: tuple[str, ...]) -> AdmittedEgressHop:
        origin = self.authorize_origin(url)
        rule = self._rules[(origin.host, origin.port)]
        if not resolved_addresses:
            raise EgressDeniedError(reason_code="dns_no_addresses", origin=origin.value)
        normalized: list[str] = []
        for value in resolved_addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise EgressDeniedError(
                    reason_code="dns_address_invalid", origin=origin.value
                ) from exc
            if not rule.allows(address):
                raise EgressDeniedError(
                    reason_code="dns_address_not_allowed", origin=origin.value
                )
            normalized.append(str(address))
        return AdmittedEgressHop(origin=origin, addresses=tuple(sorted(set(normalized))))


@dataclass(frozen=True)
class _CompiledOriginRule:
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]

    @classmethod
    def from_contract(cls, rule: EgressOriginRule) -> "_CompiledOriginRule":
        return cls(
            networks=tuple(
                ipaddress.ip_network(value, strict=True)
                for value in rule.allowed_ip_networks
            )
        )

    def allows(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(
            address.version == network.version and address in network
            for network in self.networks
        )


def _origin_from_url(url: str) -> ExactHttpsOrigin:
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https":
            raise EgressDeniedError(reason_code="https_required")
        if parsed.username is not None or parsed.password is not None:
            raise EgressDeniedError(reason_code="userinfo_forbidden")
        if parsed.fragment:
            raise EgressDeniedError(reason_code="fragment_forbidden")
        if parsed.hostname is None or "*" in parsed.hostname:
            raise EgressDeniedError(reason_code="exact_host_required")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        return ExactHttpsOrigin(host=host, port=parsed.port or 443)
    except EgressDeniedError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise EgressDeniedError(reason_code="url_invalid") from exc
