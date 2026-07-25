"""Production deployment contracts, validation and pure choreography."""

from proof_agent.deployment.choreography import (
    BlueGreenChoreographer,
    BlueGreenOperations,
    DeploymentActionError,
)
from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
    validate_deployment_compatibility_freshness,
)
from proof_agent.deployment.gateway import (
    AtomicNginxGatewaySwitcher,
    GatewayRouteObservation,
    GatewayRoutingGeneration,
    GatewaySurface,
    GatewaySwitchError,
    GatewaySwitcher,
    NginxGatewayControl,
    render_gateway_include,
)
from proof_agent.deployment.state import (
    BlueGreenDeploymentRequest,
    BlueGreenDeploymentResult,
    CandidateBinding,
    DeploymentOutcome,
    DeploymentSlot,
    DeploymentStepName,
    DeploymentStepRecord,
    DeploymentStepStatus,
    rollback_asset_retention_deadline,
)

__all__ = [
    "AtomicNginxGatewaySwitcher",
    "BlueGreenChoreographer",
    "BlueGreenDeploymentRequest",
    "BlueGreenDeploymentResult",
    "BlueGreenOperations",
    "CandidateBinding",
    "DeploymentActionError",
    "DeploymentOutcome",
    "DeploymentSlot",
    "DeploymentStepName",
    "DeploymentStepRecord",
    "DeploymentStepStatus",
    "GatewayRouteObservation",
    "GatewayRoutingGeneration",
    "GatewaySurface",
    "GatewaySwitchError",
    "GatewaySwitcher",
    "NginxGatewayControl",
    "deployment_compatibility_sha256",
    "load_deployment_compatibility_manifest",
    "render_gateway_include",
    "rollback_asset_retention_deadline",
    "validate_deployment_compatibility_freshness",
]
