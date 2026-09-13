# Knowledge connection authorization verification — 2026-09-12

[KNOWN | HIGH] `LOCAL_VERIFIED` for the development configuration-to-connection flow
approved in this conversation and ADR-0256. Production automatic policy authoring and
answer-quality validation are outside this development repair.

## Delivered behavior

- A plain binding save grants no network authority. Save-and-authorize checks Agent
  edit and Egress Policy edit permissions, resolves DNS on a worker thread, then commits
  binding, canonical binding digest grant and audit through the existing Draft CAS/UoW.
- Grants are server-owned Draft fields, absent from editable YAML. Failed validation,
  forged grant input and stale revision do not authorize. Binding edits/removal revoke
  corresponding grants. Already-composed clients reread grant authority on requests.
- Only external Knowledge uses these grants. Explicit server transports/policy files
  retain precedence; production cannot activate development grants.
- Public addresses can rotate. All DNS answers are checked before a TLS-hostname-verified,
  pinned request. Loopback, link-local, private, multicast and unsafe IPv6 transition
  addresses are denied. Explicit local-proxy permission is restricted to the two built-in
  SaaS origins and the development proxy address class, including mapped/translated IPv4.
- Save-and-authorize automatically checks the saved revision's credential and performs
  one fixed synthetic provider query per binding. Separate checks can be retried.
  Responses contain only statuses, never provider payloads or credential values.
- The Knowledge page shows authorization and connection status, preserves failed edits,
  restores the saved proxy option, and hides stale checks after editing. Validation
  detects missing authorization and links back to connection configuration.

## Evidence

The tested source snapshot is recorded in
`evidence/connection-authorization-source-sha256.json`. Several shared files also contain
pre-existing uncommitted work; their hashes identify the tested workspace, not ownership
of every change in those files.

| Check | Result |
| --- | --- |
| Initial API RED | New authorize payload rejected; connection-check route absent; 4 expected behavioral failures |
| Initial UI RED | Explicit authorization control absent |
| IPv4-translated private-address regression RED | `::ffff:0:7f00:1` was incorrectly admitted; fixed by evaluating embedded IPv4 |
| Affected backend suites | 313 passed, 4 conditioned skips |
| Final backend `.venv/bin/pytest tests/ -q` | 2966 passed, 102 skipped, 2 deselected; 2 existing dependency/serialization warnings |
| Final Dashboard `npm run test -w proof-agent-dashboard` | 269 passed across 40 files |
| `npm run build:dashboard` | Passed TypeScript and Vite build; existing bundle-size advisory |
| Scoped Ruff; `.venv/bin/mypy proof_agent` | Passed; 417 Python source files type-checked |
| `python3 scripts/check-domain-contexts.py`; `git diff --check` | Passed |

The initial full backend run was sandbox-bound: eight existing local HTTP/MCP tests
could not bind sockets. Final execution permitted loopback binding and all tests passed.
The additional initial production response-shape failure was repaired by omitting the
new server-owned field when empty, preserving the previous empty Draft contract.

## Real development surface

[KNOWN | HIGH] Using ego-browser against the existing local gateway, the operator flow
saved the current Agentset binding at Draft revision 36 with the explicit local-proxy
option. The page displayed authorized and connection available; the real server-owned
credential and fixed synthetic Agentset Search succeeded. No key was read by the agent,
no `.env` was inspected, and no remote content was returned in diagnostics.

Rendered screenshot inspection found readable controls and no horizontal overflow.
Reload preserved the proxy option. On the Validation page, entering a question enabled
Run validation with no authorization alert; the temporary question was cleared without
submission. No real model replay, Agent publication or answer-quality claim is included.
The isolated backend regression does execute the normal Validation route and verifies
HTTP 200 after authorization with a synthetic provider response.

## Review and remaining boundary

Self-review, without independent agent review, closed: IPv4-translated address bypass;
Draft refresh repeatedly fetching an older projection; loss of saved proxy-option
display; and the empty-field production contract drift. Regression tests cover the first,
conflict/edit preservation, proxy projection, and the production contract respectively.

Authorization follows the existing local configuration persistence guarantees; it is
not a new crash-durability or production release claim. DNS resolution uses the existing
system resolver on a worker thread; OS resolver timing is not a hard application deadline.
No external model replay, production deployment, Git commit or push was performed.
