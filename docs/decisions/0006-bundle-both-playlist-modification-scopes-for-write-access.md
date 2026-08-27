# ADR 0006 - Bundle both playlist modification scopes for write access

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing a whole-product write bundle, resource-aware scope checks, and
upstream-only enforcement, Yuval Moran selected the whole-product bundle with "A" on 2026-08-27
UTC.

## Context

The product exposes one playlist-write tool set to each authorized user: create a public or private
playlist, add and remove items, and update playlist metadata or visibility. The current Spotify
authorization request includes both `playlist-modify-public` and `playlist-modify-private`, and the
MCP write checker fails every mutation locally unless the stored grant contains both scopes.

Spotify describes the scopes separately as write access to public and private playlists. Its create
reference explicitly says private creation needs `playlist-modify-private` and collaborative
creation needs both scopes. The current add, remove, and change-details references list both scopes
without defining their Boolean relationship or every visibility-transition and collaborative case.
Fetching playlist metadata merely to choose a local scope would consume the Development quota,
introduce stale-state races, and still would not resolve the undocumented cases.

The initial one-to-five-user cohort receives the complete product rather than individual
write-capability profiles. No current requirement calls for public-only, private-only, or read-only
Spotify authorization. The supporting inventory is recorded in the
[SPM-5 Spotify Web API audit](../migration/spm-5-spotify-web-api-audit-2026-08-25.md).

## Decision drivers

- Support the complete public-and-private playlist feature set for every initial authorized user.
- Keep the consented write boundary explicit and predictable.
- Avoid inferring undocumented Spotify scope combinations or visibility-transition rules.
- Avoid extra metadata requests, stale-cache authorization decisions, and Development-quota use.
- Preserve current public behavior while OAuth and public-contract implementation remain plan-first.
- Prefer the simplest policy that satisfies the actual one-to-five-user product.
- Keep a clear revisit path if granular user capability profiles become a real requirement.

## Options considered

### Treat both scopes as one product-level write-capability bundle

Request both modification scopes and require both before dispatching any playlist mutation. This
preserves the complete product, current behavior, and deterministic local preflight without extra
Spotify requests. It denies a partially scoped token even when one operation might succeed and
therefore grants more capability than a public-only or private-only user would need.

### Enforce the scope matching each playlist and operation

Use the requested visibility for creation and discover the current visibility for existing
playlist mutations. This offers the strongest operation-level least privilege and makes partial
tokens useful. It adds metadata requests or cache authority, race conditions, transition rules,
and unsupported assumptions for cases Spotify does not specify completely.

### Let Spotify enforce the resource-specific scope

Require at least one modification scope locally, submit the mutation, and treat Spotify's response
as authoritative. This avoids inventing a Boolean rule and avoids a visibility lookup. It exposes
operations that can fail only after an upstream request, consumes quota on predictable failures,
and makes user-facing behavior depend on the target playlist and Spotify's error detail.

## Decision

Treat both modification scopes as one product-level write-capability bundle.

1. A user who can invoke Spotify playlist-write tools must grant both
   `playlist-modify-public` and `playlist-modify-private`. The initial product has no public-only,
   private-only, or read-only Spotify authorization profile.
2. Request both scopes during Spotify authorization and preserve both in the stored grant. A
   partial grant is not a supported write-enabled state even when Spotify might accept a particular
   operation with only one scope.
3. Before `spotify.create_playlist`, `spotify.add_tracks`, `spotify.remove_tracks`, or
   `spotify.update_playlist` calls Spotify, require the complete bundle. If either scope is absent,
   fail locally with a sanitized reauthorization message and do not spend an upstream request.
4. Do not fetch or trust playlist visibility merely to weaken the local scope preflight. Do not
   treat cache metadata as authorization evidence, and do not encode unverified scope rules for
   visibility transitions or collaborative playlists.
5. Possession of both scopes is necessary but not sufficient. Spotify remains authoritative for
   ownership, collaboration, playlist state, account entitlement, and every other resource-level
   authorization rule; an upstream 403 must remain a normal handled possibility.
6. Read-only playlist tools continue to depend only on their accepted read-scope and resource
   rules. This write bundle grants no new endpoint, collaborative-creation feature, item type,
   public response, or bypass of existing user isolation.
7. The current checker already implements the selected policy. Any implementation work must add
   the complete decision-table coverage and documentation required below without expanding this
   ADR into a new role or capability system.
8. A future read-only or restricted-write user profile requires an explicit product requirement,
   separate public behavior, and an accepted amendment or superseding ADR before changing requested
   scopes or write-tool availability.
9. This decision records the target authorization boundary only. It grants no provider-console,
   account, token, credential, production, OAuth rollout, public-contract, deployment, or data
   access authority.

## Consequences

- All initial users receive one predictable playlist-write capability covering public and private
  playlists.
- Current local preflight remains valid and incurs no additional Spotify request or cache
  dependency.
- Consent is broader than a user who wants only public or only private mutations would need. That
  is accepted because the current product offers the full write set as one capability.
- Tokens missing either scope must reauthorize before any playlist write, even when an isolated
  Spotify operation might otherwise succeed.
- The policy avoids speculative scope logic, but it does not prevent Spotify from rejecting a
  request for ownership, collaboration, entitlement, or resource-state reasons.
- A later granular authorization model will require explicit product design, public-tool behavior,
  migration for existing grants, and more extensive tests; it is not prebuilt now.

## Validation

The implementation and rollout plans must include:

- an authorization decision table covering both scopes, public-only, private-only, neither, a
  missing token, an empty scope string, and unrelated scopes;
- focused tests for every playlist-write tool proving the complete bundle proceeds and every
  partial or missing bundle fails before Spotify client construction or request dispatch;
- exact requested-scope and persisted-grant tests for initial authorization and token refresh;
- regression tests proving playlist read tools do not acquire the write-bundle requirement;
- sanitized error tests that identify the missing scope and reauthorization action without tokens,
  Spotify identifiers, account data, or listening data;
- upstream 403 tests proving the complete local bundle is never treated as proof of resource-level
  authority; and
- public MCP/API compatibility tests proving this policy record does not change tool schemas,
  success payloads, or the existing outward error envelope.

## Rollback / revisit trigger

This ADR formalizes existing behavior, so recording it requires no runtime rollback. Before any
future behavior change, stop the change and amend or supersede this record rather than silently
weakening the bundle. If an implementation based on a superseding policy is rolled back, restore
the complete-bundle preflight and preserve existing grants; do not mutate provider settings or
tokens as an application-code rollback shortcut.

Revisit the decision if the product adds a read-only or restricted-write user profile, Spotify
publishes authoritative per-operation scope semantics that make the bundle materially unnecessary,
measured consent friction blocks the initial cohort, public/private playlist support is removed,
or privacy/security requirements demand a narrower grant model.

## Related decisions

- [ADR 0003](0003-adopt-staged-account-id-migration.md) governs the bounded Spotify
  reauthorization and account-linking migration.
- [ADR 0004](0004-separate-provider-identities-and-minimize-profile-retention.md) removes unrelated
  profile scopes and data after its cohort gate; it does not remove demonstrated playlist-write
  scopes.
- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) selects the
  Development common denominator and makes avoiding unnecessary quota use a release concern.
- The dedicated public MCP/API compatibility decision continues to own outward tool/error behavior.
  Episode/embed behavior and Audio Features provider/default policy remain separate owner decisions.
