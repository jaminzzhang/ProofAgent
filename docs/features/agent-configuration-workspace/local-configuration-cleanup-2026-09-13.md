# Local configuration cleanup — 2026-09-13

[KNOWN | HIGH] The local Agent list returned HTTP 500 because the default
`runs/config` contained an incompatible legacy draft validation record. Its old
published package also declared the removed `package_knowledge_sources` authority.
Reproducing the read in a fresh process confirmed that restarting alone was
insufficient.

## Local configuration changes

The default store was replaced with the compatible configuration from
`runs/dify-verification/config`. The compatible model connection from the old
default store was retained. The resulting default store contains one draft, two
published versions and two model connections. The active version remains
`version_31a7d2a9`, and the draft remains `draft_a701d51c`.

The incompatible draft, old publication, package-local Knowledge Source and
compiled package were removed from the active default store. The original store
was archived under the ignored local `runs/config-backups/20260913T194723/`
directory for recovery. Configuration contents and credentials are not committed.
Historical traces and published package contents were not rewritten.

The running API now uses `runs/config`. The prior
`runs/dify-verification/config` is a compatible pre-cutover snapshot; later edits
belong in the running service's default store. Run history remains in its existing
directory. Use the following API command to preserve the configured Agent rather
than reapplying the development example seed:

```sh
.venv/bin/proof-agent server \
  --config-dir runs/config \
  --history-dir runs/dify-verification/history \
  --no-seed-example-agent
```

This command starts the API only. The local gateway and Dashboard/Operator Chat
frontends must also be running for `http://127.0.0.1:18080/agents`.

## Verification

[KNOWN | HIGH] At cleanup time, both stores passed current draft, publication,
model and tool record loading. Every Agent YAML in the resulting default store
passed the current manifest loader. Six TestClient routes per store returned 200:
Agent list, model connections, tool sources, versions, draft detail and Chat Agents.

The restarted gateway returned 200 for `/agents`, `/operator`, Agent list,
model connections, versions and draft detail. Browser inspection confirmed the
rendered Agent list contained one Agent, one draft and the preserved active version,
with no API error. External-provider calls and production release were not tested.

This is dated local verification, not a persistent guarantee about ignored runtime
data. No application code or public contract changed in this cleanup.
