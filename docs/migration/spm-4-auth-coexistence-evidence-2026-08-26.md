# SPM-4 authentication coexistence evidence - 2026-08-26

## Scope and evidence labels

This note evaluates the browser-authentication edge for ADR 0002. It does not authorize an Azure
apply, Google or Spotify console mutation, credential access, production access, public-contract
change, or deployment.

- **Measured** - observed in this repository at the current SPM-4 worktree head.
- **Official** - stated by current Microsoft or oauth2-proxy documentation retrieved on
  2026-08-26 UTC.
- **Inferred** - an architectural conclusion that still requires the named plan, implementation,
  and release evidence.

## Current contract

- **Measured:** Caddy owns the public route split. `/healthz`, `/auth/*`, `/api/*`, and `/mcp/*`
  bypass Google forward authentication. `/admin/*` and protected Explorer routes use
  `oauth2-proxy` forward auth.
- **Measured:** `oauth2-proxy` authenticates Google accounts and enforces an external email
  allowlist. It emits `X-Auth-Request-Email` to the protected Python UI.
- **Measured:** the Explorer `GoogleAuthMiddleware` sends that email to the API's internal
  `/auth/exchange-google` operation. The API maps the email to an existing user and returns the
  application's own access and refresh JWTs.
- **Measured:** application JWT/API-token middleware is deliberately permissive at the middleware
  layer; route dependencies enforce authorization. Browser JWT cookies, `smcp_` API tokens, MCP
  bearer tokens, Spotify OAuth, and optional token/basic admin authentication are separate from
  the Google edge session.
- **Measured:** the current exchange can optionally use a single-user fallback. Retaining,
  restricting, or deleting that identity behavior remains an explicit authentication decision;
  it must not be inherited accidentally.

This means Google is already an authentication input to the application identity and
authorization model rather than the sole authorization system. The target can replace the Google
edge without replacing Spotify OAuth, JWTs, RBAC, API tokens, or MCP authentication at the same
time.

## Official Azure constraints

| Fact | Consequence |
|---|---|
| Azure Container Apps built-in authentication supports Google at `/.auth/login/google`, establishes a browser session cookie, and injects authenticated identity headers. External requests cannot set those protected headers. | It can replace the Google-login and trusted-identity-header responsibilities of `oauth2-proxy`. The application must still perform its own account allowlist/link and authorization checks. [Container Apps authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication) |
| Container Apps authentication can allow unauthenticated traffic and defer authorization to application code. The platform restriction otherwise applies to all requests. | The backend can keep public health, Spotify callback, JWT/API-token, and MCP bearer paths while accepting Google identity only on the browser-session bridge. Global "require authentication" is not compatible with the mixed public and bearer-token surface. [Container Apps authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication) |
| The Container Apps auth resource model exposes `excludedPaths`, Google registration, callback/route settings, cookie expiration, and explicit allowed external redirects. | The behavior is IaC-addressable, but callback, redirect, cookie, and exclusion semantics still require exact tests. [Container Apps auth resource](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps-auth-configs/get?view=rest-resource-manager-containerapps-2025-07-01) |
| Google registration for Container Apps requires a Google client ID/secret and the ACA `/.auth/login/google/callback` URI. | DigitalOcean and Azure callbacks must coexist during rehearsal. Prefer a separate Azure Google OAuth client so rollback does not mutate the working DigitalOcean registration. [Container Apps Google authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication-google) |
| Static Web Apps can use a custom Google provider only on Standard and can link a Container App under `/api`. Linked API requests have a 45-second maximum, support only HTTP, and SWA has a 30-MB request-size limit. | SWA authentication plus a linked backend is not a complete edge for the current 500-MiB import allowance, long operations, direct MCP/SSE, `/auth/*`, or `/admin/*`. It would require a second direct-ACA auth/exchange path and two browser transport modes. [SWA custom authentication](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-custom), [SWA API constraints](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview), [SWA quotas](https://learn.microsoft.com/en-us/azure/static-web-apps/quotas) |
| oauth2-proxy can reverse proxy to an upstream and supports method/path-specific auth bypasses. | It can reproduce the Caddy route split as a dedicated public Container App, but becomes another warm workload and another public routing dependency. [oauth2-proxy configuration](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/) |

Container Apps' optional token store is not required for this design. The application needs the
verified Google principal and the platform session, not retained Google access/refresh tokens.
Leaving the token store disabled avoids a separate SAS-backed Blob token-retention boundary.

## Options

### A - Dedicated `oauth2-proxy` Container Apps edge

Run `oauth2-proxy` as the public `api.<domain>` Container App. It sends every request to an
internal API Container App and bypasses Google authentication for an exact method/path allowlist
covering health, Spotify/JWT auth, REST, and MCP bearer routes. Protected browser-session routes
receive the current Google identity header.

**Benefits**

- Closest behavioral match to Caddy plus `oauth2-proxy`.
- Reuses the current Google provider, allowlist, cookie, and header model.
- The internal API has no direct public-origin bypass around the proxy.
- Gives the lowest-risk first Azure auth landing if native authentication cannot pass its gates.

**Costs and risks**

- Adds a continuously warm workload, public hop, image lifecycle, health target, logs, and
  availability dependency.
- The skip-route list becomes security-critical and must reproduce Caddy semantics exactly.
- React still needs a new Google-to-application-JWT bridge because the current bridge lives in the
  Python Explorer service.
- "Retire later" can become indefinite; a sunset gate reduces but does not eliminate that risk.
- A proxy-wide outage takes REST, uploads, MCP, and browser authentication down together.

**Rollback**

- Strongest compatibility rollback: restore the previous proxy and API revisions independently.
- A mandatory removal decision after SPM-10 could prevent indefinite retention, but it would be
  another plan-first decision and migration.

### B - Container Apps Google authentication plus the existing application auth model

Do not deploy `oauth2-proxy` to Azure. Enable Google on the public API/MCP Container App, but set
platform authorization to allow unauthenticated requests. Container Apps owns only Google login,
callback, session, and trusted identity headers. A narrow API bridge accepts those headers only
after platform validation, enforces the approved email/account-link policy, and issues the existing
application JWT cookies. The application continues to authorize REST/admin routes and continues to
validate Spotify OAuth, JWTs, API tokens, and MCP bearer tokens.

Use sibling custom hosts such as `app.<domain>` and `api.<domain>`. React calls the API host with
credentials. Keep the application cookies host-only to the API where possible. The API uses an
exact credentialed-CORS allowlist, origin/CSRF checks for cookie-authenticated unsafe methods, and
no wildcard origins. `/.auth/*` belongs to the platform; the API owns all application paths.

**Benefits**

- Removes Caddy and `oauth2-proxy` from the Azure steady state without replacing the entire
  application auth system.
- Reuses the existing architectural seam: trusted Google identity becomes application JWT/RBAC.
- No extra proxy Container App, public hop, proxy image, or skip-route configuration.
- Direct ACA ingress remains available for MCP HTTP/SSE and large imports.
- The platform strips spoofed identity headers before application code sees the request.

**Costs and risks**

- It is an authentication implementation change and therefore requires a dedicated accepted auth
  plan plus exact contract tests before release.
- `Allow unauthenticated` means the application is the authorization enforcement point. One
  missing route dependency could expose data, so a deny-by-default route inventory and negative
  tests are mandatory.
- Google authentication alone does not preserve the current email allowlist or DB-account link;
  the bridge must enforce both. The single-user fallback must be explicitly accepted or disabled.
- Separate frontend/API origins require exact CORS, cookies, CSRF, callbacks, and browser tests.
- It introduces an Azure-specific login adapter, although the application's JWT/RBAC core remains
  portable.

**Rollback**

- Keep the working DigitalOcean `oauth2-proxy` and Google OAuth client unchanged through Azure
  rehearsal. Use a separate Azure Google client/callback.
- Before production writes, rollback is the established DigitalOcean route. After first Azure
  write, authentication rollback is an immutable Azure API revision/config rollback; it does not
  make DigitalOcean writable again.
- Do not build a speculative Azure `oauth2-proxy` manifest. If native authentication fails a
  concrete gate, preserve the failure evidence and require an accepted amendment before building
  or activating that fallback.

### C - Application-owned Google OIDC

Implement the Google authorization-code flow, session handling, callback, token validation, and
logout directly in the API, then issue the existing application JWTs.

**Benefits**

- Cleanest cloud-portable steady state and one application-owned auth flow.
- Maximum control over callbacks, sessions, claims, and account-link policy.
- No proxy workload and no Azure Easy Auth dependency.

**Costs and risks**

- Largest security-sensitive implementation and maintenance burden.
- The application becomes responsible for OIDC discovery/key rotation, nonce/state/PKCE, provider
  errors, session security, token validation, logout, and future provider behavior.
- Duplicates a managed capability without a current product requirement for cloud portability.
- Broadens SPM-4/SPM-10 and makes auth failure harder to separate from the backend rewrite choice.

**Rollback**

- Requires an application revision rollback and preservation of compatible session/account-link
  data. It has no independent platform/proxy rollback seam.

## Why Static Web Apps authentication is not the recommended shortcut

Using SWA Google auth and its linked-ACA `/api` proxy looks attractive because ordinary browser
calls become same-origin. It is incomplete for this product: SWA limits requests to 30 MB and
linked API execution to 45 seconds, only proxies `/api`, and does not carry MCP SSE/WebSocket. The
app still needs direct ACA paths for imports, `/auth`, `/admin`, and MCP, plus a secure way to
exchange the SWA principal into an API-host session. That is more topology and two auth transports,
not less. SWA remains the static host; it should not be the backend authentication authority.

## Recommendation

Select **B**, subject to a dedicated accepted authentication plan and mandatory SPM-6/SPM-10
gates. It removes the proxy from the target without attempting a full auth rewrite. The current
Google-to-JWT seam makes the change narrower than it first appears: the trusted header source moves
from `oauth2-proxy` to Container Apps, while account authorization, application JWTs, Spotify OAuth,
API tokens, and MCP bearer tokens remain explicit application contracts.

The fallback is **A only if B fails a release gate**. Do not run A indefinitely beside B, and do
not choose C without a portability or provider requirement that justifies owning the full OIDC
security lifecycle.

## Small-cohort and YAGNI reassessment

The owner expects only 1-5 initial users, extremely gradual growth, and explicitly wants the first
version to follow YAGNI. That changes the size of the necessary implementation, but not the
authentication boundary:

- It makes forced re-login during an authorized cutover acceptable; cross-system session migration
  is unnecessary.
- It makes a manually maintained, secret-backed email allowlist adequate. There is no current need
  for invitation workflows, self-service provisioning, group synchronization, tenant federation,
  multiple identity providers, or an authorization-management UI.
- It permits a small named-user pilot against the Azure callback before cutover.
- It does not justify weaker route authorization, origin/CSRF controls, secret handling, or negative
  tests. Authentication defects are not made safe by a small user count.
- It makes a continuously warm `oauth2-proxy` workload less attractive: its fixed topology,
  operations, and consumption do not shrink with the number of users.

### Two possible staged paths

**Temporary Azure A, then B** is technically possible, but it builds and validates two Azure auth
edges. The public custom-domain binding, callback, trusted header, proxy bypass rules, health
checks, rollback, and observability are first proved for `oauth2-proxy` and then changed and proved
again for Container Apps authentication. React still needs an application-session bridge. This is
locally familiar but is more total work and creates the exact indefinite-transition risk the owner
identified elsewhere.

**Minimal B, introduced gradually** is the recommended YAGNI path:

1. Keep the current DigitalOcean Caddy/`oauth2-proxy` flow unchanged and authoritative.
2. Build only the minimum Azure B adapter: Google server-directed login, trusted-header parsing,
   one secret-backed allowlist, existing-user email match, existing application JWT issuance, and
   logout. Disable the single-user fallback in the Azure target unless explicitly accepted.
3. Do not add provider-token storage, invitations, self-service signup, automatic account
   provisioning, group/role synchronization, multiple providers, session migration, or SWA-linked
   API routing.
4. Use a separate Azure Google OAuth client and a small named-user test environment. Have the 1-5
   users sign in again; do not migrate Google or application sessions.
5. Move route groups through SPM-10 while Azure B remains behind a non-production hostname. Cut
   over only after the complete route/auth matrix and SPM-6/SPM-10 gates pass.
6. Before the first Azure write, the rollback remains the unchanged DigitalOcean system. After the
   first Azure write, roll back the Azure application/auth revision under ADR 0002's accepted
   forward-recovery rule.

This is gradual coexistence at the **environment and route-validation level**, not two production
auth stacks inside Azure. It reaches B directly while keeping the working A implementation as the
pre-cutover rollback asset. Option A should be implemented in Azure only if B fails a concrete
gate, not merely because A already exists on DigitalOcean.

## Mandatory plan and release gates for B

1. Freeze a complete route/auth matrix for anonymous, Google session, application JWT cookie,
   refresh cookie, `smcp_` token, MCP bearer/JWT, admin token/basic, Spotify callback, health, and
   internal-only operations. Every data route must have an explicit denying negative test.
2. Use a separate Azure Google OAuth client and callback while DigitalOcean stays authoritative.
   Name the Google-console and DNS owners; do not mutate either registration during repository
   delivery.
3. Prove the ACA identity headers cannot be supplied by an external client and that the bridge
   rejects missing, malformed, unverified, unapproved, or unlinked identities.
4. Decide the exact allowlist/account-link authority and the single-user fallback in the dedicated
   auth ADR. No unknown Google identity may receive an application JWT by default.
5. Prove sibling custom-domain behavior for `app.<domain>` and `api.<domain>`: credentialed CORS,
   preflight, host-only cookies, `Secure`, `HttpOnly`, `SameSite`, refresh path, expiry, logout,
   origin/CSRF rejection, callback allowlists, and browser privacy modes.
6. Keep the ACA auth token store disabled unless a later accepted requirement needs provider
   tokens. Prove Google login/session/logout without retaining provider access or refresh tokens.
7. Run SPM-6 conformance for health, REST, upload, MCP bearer/API-token, current Streamable HTTP,
   optional SSE/reconnect, malformed auth, and concurrent browser/MCP sessions through the exact
   public API host.
8. Run SPM-10 route-by-route browser parity and rollback tests. The old Python UIs and
   `oauth2-proxy` remain available on DigitalOcean until React plus B passes the accepted cutover
   gate.
9. Rehearse an Azure revision/config rollback. After the first Azure production write, rollback
   must remain in Azure and follow ADR 0002's forward-recovery boundary.
10. If any gate fails, stop the release. Either correct B or amend the accepted auth decision to
    activate A; do not silently expose a route or make DigitalOcean writable.

## Owner decision evidence

On 2026-08-26 UTC, the owner stated that B looks like the best eventual target and asked whether an
initially simpler, gradual path is possible for a 1-5-user, very-slow-growth product under YAGNI.
After reviewing the minimum viable B scope, deferred features, environment-level coexistence,
rollback boundary, and the cost and indefinite-transition disadvantages of disposable Azure A,
Yuval Moran approved the refined package with **"approved"**. This selects minimum viable B
introduced gradually while the existing DigitalOcean A remains authoritative until cutover. It
does not authorize Azure apply, Google-console mutation, credentials, deployment, production
access, or an Azure `oauth2-proxy` fallback.
