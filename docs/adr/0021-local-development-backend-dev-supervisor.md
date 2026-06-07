# Local Development Backend Startup Uses a Dev Supervisor

Proof Agent local development will use `proof-agent dev` as the default backend startup entry point, loading `.env` and supervising both the API server and the Knowledge Worker. We chose an explicit dev supervisor instead of making `proof-agent server` implicitly start the worker so the production-shaped API command remains single-purpose, while local Dashboard uploads still get immediate Local Index processing by default.

The dev supervisor starts the API and Knowledge Worker as separate child processes, fails fast when either service cannot start, and stops both services together on interruption. The Dashboard and Chat frontend dev servers remain separate commands because their Node/Vite lifecycle, dependency management, and logs are different from the Python backend runtime.
