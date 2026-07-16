from __future__ import annotations

from enum import StrEnum
import ipaddress
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel


class ExactHttpsOrigin(StrictFrozenModel):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)

    @classmethod
    def parse(cls, value: str) -> "ExactHttpsOrigin":
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https":
            raise ValueError("production egress origin must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("production egress origin cannot contain userinfo")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("production egress origin cannot contain path, query, or fragment")
        if parsed.hostname is None or "*" in parsed.hostname:
            raise ValueError("production egress origin requires one exact host")
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower()
            port = parsed.port or 443
        except (UnicodeError, ValueError) as exc:
            raise ValueError("production egress origin is invalid") from exc
        return cls(host=host, port=port)

    @property
    def value(self) -> str:
        return f"https://{self.host}:{self.port}"


class EgressOriginRule(StrictFrozenModel):
    origin: ExactHttpsOrigin
    allowed_ip_networks: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_networks(self) -> "EgressOriginRule":
        normalized: list[str] = []
        for value in self.allowed_ip_networks:
            try:
                network = ipaddress.ip_network(value, strict=True)
            except ValueError as exc:
                raise ValueError("egress address range must be one strict CIDR") from exc
            normalized.append(str(network))
        if len(normalized) != len(set(normalized)):
            raise ValueError("egress origin rule contains duplicate address ranges")
        return self


class EgressPolicyVersion(StrictFrozenModel):
    version_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    rules: tuple[EgressOriginRule, ...] = Field(default_factory=tuple)
    created_at: str
    created_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_origins(self) -> "EgressPolicyVersion":
        identities = [(rule.origin.host, rule.origin.port) for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("egress policy contains duplicate exact origins")
        return self


class ProductionToolEffect(StrEnum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SEND = "send"
    SETTLE = "settle"
    EXECUTE = "execute"
