# Production Browser Authentication Uses Backend-Managed OIDC Sessions

Accepted.

[FRAME | HIGH] The production Gateway and API complete the OIDC Authorization Code flow, validate the external identity, and keep OIDC tokens and trusted claims server-side in a Backend-Managed Operator Session stored through Production Transactional State Store. The browser receives only an opaque `Secure`, `HttpOnly`, and `SameSite` session cookie; access and refresh tokens are never exposed to frontend JavaScript or browser storage. Dashboard, Operator Chat, and browser APIs use one production origin, wildcard CORS is disabled, and state-changing commands require CSRF protection in addition to the session cookie.

[FRAME | HIGH] An operator session expires at the earlier of seven days after login or 24 hours without accepted operator activity. The backend session record is the authority for both limits; frontend timers may improve the user experience but cannot extend or override server-side expiry.

[FRAME | HIGH] Provider-derived identity claims must have been successfully refreshed or revalidated within the preceding hour before they may authorize a protected operation. A refresh failure, revoked identity, or failed validation prevents further protected operations until successful authentication; a seven-day session may not preserve stale authorization. Proof Agent combines the fresh trusted claims with the currently active permission mapping on each request.
