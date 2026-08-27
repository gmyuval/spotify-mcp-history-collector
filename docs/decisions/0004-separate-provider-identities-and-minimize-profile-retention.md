# ADR 0004 - Separate provider identities and minimize Spotify profile retention

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing compatibility-first retention, data-minimized provider separation,
and stable Google linking with continued Spotify profile retention, Yuval Moran selected the
data-minimized provider-separation option with "B approved" on 2026-08-27 UTC.

## Context

The current application conflates attributes from two identity providers. Spotify OAuth stores
profile `email`, `country`, and `product` directly on `users`. The Google edge then treats that
Spotify-provided email as the join key from a Google-authenticated browser session to the internal
`users.id`. An optional single-user fallback can issue application tokens even when no email
matches.

Spotify's current profile reference marks `email`, `country`, and `product` deprecated. The
February 2026 Development Mode migration guide says affected integrations no longer receive those
fields, and Spotify describes the email as unverified. Google's OpenID Connect reference says an
email can change and is not a safe primary identifier; it names the provider subject (`sub`) as the
stable user key. These are different provider identities and must not be joined automatically by a
mutable profile attribute.

[ADR 0003](0003-adopt-staged-account-id-migration.md) already makes Spotify `account_id`
authoritative for Spotify account linking while preserving internal `users.id`. [ADR
0002](0002-azure-target-architecture-and-migration-boundaries.md) selects a minimum viable Azure
Container Apps Google-authentication bridge but deliberately leaves its allowlist, account-link,
and single-user-fallback policy to a dedicated decision. This ADR resolves that policy and the
Spotify profile-retention boundary. It does not implement either migration.

The supporting repository inventory is in the
[SPM-5 Spotify Web API audit](../migration/spm-5-spotify-web-api-audit-2026-08-25.md), and the
current-to-target authentication seam is in the
[SPM-4 authentication coexistence evidence](../migration/spm-4-auth-coexistence-evidence-2026-08-26.md).

## Decision drivers

- Prevent mutable or unverified email attributes from joining authentication identities.
- Keep Spotify identity, Google browser identity, and internal application identity explicit.
- Minimize retained PII and requested Spotify scopes without breaking current public contracts.
- Preserve the working DigitalOcean authentication path until a replacement passes its gates.
- Give the initial one-to-five-user cohort a bounded, observable relinking path.
- Prevent temporary profile retention or email fallback from becoming indefinite.
- Avoid invitations, self-service provisioning, multi-provider management, or other unneeded
  identity-platform features.

## Options considered

### Preserve email-based linking and all current Spotify profile fields

This is the smallest immediate change and preserves every populated profile screen. It links two
providers through an unverified or mutable field, depends on fields affected Development Mode no
longer returns, retains unnecessary PII, and has no durable completion path.

### Separate provider identities and minimize Spotify profile retention

This makes each provider's stable subject explicit, maps both to internal `users.id`, removes the
Spotify email scope after a bounded transition, and stops retaining deprecated Spotify profile
fields. It requires an additive identity-link model, a controlled active-user relink, and a later
reviewed contraction.

### Use stable Google linking but continue Spotify profile retention

This corrects the most serious account-link risk while preserving richer profile displays where
Spotify still supplies the fields. It keeps deprecated, inconsistently available PII and the
`user-read-email` scope without a demonstrated product requirement.

## Decision

Select data-minimized provider-identity separation.

1. Preserve `users.id` as the internal application identity and foreign-key root. A Spotify
   identity and a Google identity are separate credentials linked explicitly to that internal ID;
   neither provider's email or display name is an application identity key.
2. Use Spotify `account_id` as the authoritative Spotify link under ADR 0003. Continue treating
   Spotify profile `id` and the `spotify_user_id` field as compatibility metadata until the public
   compatibility decision changes that surface.
3. Represent Google browser identity by the verified provider issuer and stable provider subject,
   mapped explicitly to exactly one internal `users.id`. Before implementation relies on an Azure
   Container Apps principal header, prove against the configured Google provider that the selected
   header or claim is stable, non-reassignable, and equivalent to the intended provider subject;
   do not infer that property from a header name.
4. Never automatically create, join, merge, or replace an application user merely because Google
   and Spotify email strings match. Disable the single-user fallback at the stable-subject
   authority switch. Conflicting, duplicate, missing, or ambiguous provider links fail closed and
   require reviewed recovery.
5. Google email may be retained separately as mutable secondary allowlist and contact metadata for
   the initial named-user cohort. It is not unique identity authority, is not copied into the
   Spotify profile fields, and an email change must not relink the provider subject to another
   user. The implementation plan must define normalization, update, allowlist, disclosure, and
   retention behavior without placing real addresses in repository or tracker evidence.
6. Use a reviewed proof-of-control flow to establish every active cohort member's Google provider
   link. Email equality alone is insufficient proof. The rollout plan must name a finite start and
   end, communication, recovery, and rollback. Reaching the end without linking every active user
   blocks the authority switch and returns the exception to the owner; it does not extend
   email-only linking indefinitely.
7. After every active cohort member has an explicit, unambiguous Google provider link:
   - make the stable Google provider link authoritative for browser-to-application exchange;
   - remove `user-read-email` from new Spotify authorization requests and reauthorize the active
     cohort so stored grants no longer depend on that scope;
   - stop ingesting or updating Spotify `email`, `country`, and `product`; and
   - retain nullable `display_name` as non-authoritative presentation metadata.
8. Retain `user-read-private` only while an accepted supported-mode and public Search contract
   requires it. Do not retain Spotify `country` or `product` merely because that scope remains
   necessary for another endpoint.
9. Existing Spotify `email`, `country`, and `product` values become frozen legacy data after
   ingestion stops and must never regain identity authority. Their deletion and any later column
   removal require a separately reviewed contraction plan, public nullable-field compatibility,
   rollback/backup evidence, privacy-safe cohort completion proof, and explicit destructive-action
   authority. The implementation plan must set a finite contraction deadline; missing it returns
   to the owner rather than silently converting temporary retention into the steady state.
10. Keep Google provider token storage disabled. The application needs the verified provider
    identity and its own JWT/RBAC session, not retained Google access or refresh tokens.
11. Implement schema, provider linking, OAuth scope changes, profile contraction, public response
    changes, or data deletion only through their separately reviewed plans and issues. This ADR
    grants no database migration, provider-console mutation, production/account access, credential
    access, deployment, or deletion authority.

## Consequences

- Spotify, Google, and application identities gain explicit authorities and cannot be silently
  joined by matching email strings.
- The target removes an unnecessary Spotify scope and deprecated Spotify profile PII while keeping
  the small named-user Google allowlist practical.
- Google email remains mutable secondary metadata and therefore needs provenance, update, and
  retention rules even though it is no longer a link key.
- An additive provider-identity mapping and proof-of-control migration increase authentication and
  recovery complexity temporarily.
- The working DigitalOcean email bridge remains the pre-switch rollback asset; it is not the Azure
  steady state.
- Existing API and UI fields may continue to exist as nullable compatibility fields after Spotify
  ingestion stops. Removing those keys remains a separate public-contract decision.
- No invitation system, self-service signup, provider-token store, automatic provisioning,
  multi-provider UI, group synchronization, or account-merging engine is selected.

## Validation

The implementation and rollout plans must include:

- proof of the exact Google issuer/subject claim delivered by the configured DigitalOcean and
  Azure authentication paths, including spoofed, missing, malformed, and changed-claim cases;
- schema constraints and concurrency tests proving one provider identity cannot map to multiple
  internal users;
- negative tests proving email equality and the single-user condition never create or change a
  stable provider link after the authority switch;
- proof-of-control, conflict, retry, duplicate, rollback, and recovery tests for every active-user
  relink state without exposing identifiers or email addresses in evidence;
- a provider-email-change test proving the stable link remains attached to the same internal user
  while allowlist policy fails closed or follows its explicit reviewed update rule;
- exact requested-scope and stored-grant tests before and after `user-read-email` removal, while
  retaining `user-read-private` only for the accepted Search requirement;
- persistence tests proving Spotify email, country, and product stop updating, while display name,
  `account_id`, and compatibility metadata follow their accepted policies;
- nullable public-field and browser/API regression tests before any legacy-value contraction;
- sanitized completion metrics and a finite contraction deadline; and
- rehearsed application rollback before the authority switch and reviewed forward recovery after
  destructive contraction.

## Rollback / revisit trigger

Before the stable-Google-subject authority switch, stop the new link rollout and keep the existing
DigitalOcean email bridge authoritative. Preserve every verified provider mapping for a later
retry; do not drop the additive mapping merely to roll back application code.

After the authority switch but before legacy-value deletion, roll back only through a reviewed
authentication incident plan that preserves stable mappings. Do not silently restore email-only
joining or the single-user fallback. After legacy profile values are deleted, use forward recovery;
an application rollback cannot recreate deleted PII and must not attempt to infer it.

Revisit this decision if Google changes its stable-subject contract, Container Apps cannot expose
a verified stable provider identity, the active cohort cannot complete proof-of-control linking,
Search no longer requires `user-read-private`, a new product requirement justifies retained profile
data, or privacy/legal requirements demand a different retention period.

## Related decisions

- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) selects the minimum viable
  Container Apps Google-authentication bridge and leaves this account-link policy as a release gate.
- [ADR 0003](0003-adopt-staged-account-id-migration.md) owns Spotify `account_id` linking and the
  Spotify-side active-cohort migration.
- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) selects the restricted
  Development common denominator while leaving the public Search contract separately gated.
- [ADR 0006](0006-bundle-both-playlist-modification-scopes-for-write-access.md) retains both
  demonstrated playlist-modification scopes as one initial product capability.
- Public removal or renaming of `spotify_user_id`, email, country, or product response fields
  remains part of the dedicated public MCP/API compatibility decision.
