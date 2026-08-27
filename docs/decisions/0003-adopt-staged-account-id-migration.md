# ADR 0003 - Adopt a staged `account_id` identity migration

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing the compatibility, indefinite-transition, conflict, and rollback
trade-offs, Yuval Moran accepted the staged additive migration with "staged approach is best" on
2026-08-27 UTC.

## Context

The current OAuth callback treats Spotify profile `id` as the account-linking key. The `users`
table stores it as a unique, non-null `spotify_user_id`; callback responses also expose it under
that name. Spotify's May 2026 guidance instead describes `account_id` as the public,
pseudoanonymous, immutable account-linking key and says not to link accounts by profile `id`.

Internal integer `users.id` is already the stable foreign-key root for tokens, plays, sync
checkpoints, imports, jobs, authorization records, and derived data. Replacing that internal key is
therefore unnecessary and would enlarge the migration and rollback surface. The repository has no
evidence that an existing user's Spotify profile `id` has changed, and this decision does not
authorize inspection of production accounts, tokens, credentials, or personal data.

The supporting endpoint, model, persistence, and identity inventory is recorded in the
[SPM-5 Spotify Web API audit](../migration/spm-5-spotify-web-api-audit-2026-08-25.md).

## Decision drivers

- Make the Spotify-supported immutable field authoritative for account linking.
- Prevent an identity mismatch from attaching one person's data or credentials to another person.
- Preserve the internal `users.id` graph and the current public API/MCP shape while their separate
  compatibility and retention decisions remain open.
- Give the initial one-to-five-user cohort a bounded, observable reauthorization path.
- Prevent a staged migration from becoming an indefinite dual-identity mode.
- Keep expand, authority-switch, contraction, and rollback operations separately reviewable.

## Options considered

### Continue linking by Spotify profile `id`

This has no immediate schema or login change and therefore maximizes short-term compatibility. It
conflicts with Spotify's current identity guidance, leaves a known account-linking risk in place,
and gives no completion path.

### Perform a hard coordinated cutover

This reaches the clean target quickly and avoids a dual-key interval. It requires every user to
reauthorize at once, makes an ambiguous or missing mapping a login outage, and couples schema,
authentication, public compatibility, and data recovery into one high-risk operation.

### Use a bounded staged additive migration

This retains internal keys and existing public fields while users reauthorize, permits a reversible
expand phase, and makes conflicts explicit. It temporarily adds dual-key logic and operational
state. A mandatory cohort gate and a finite rollout window are required so that "temporary" cannot
silently become permanent.

## Decision

Adopt the bounded staged additive migration.

1. Add a nullable, unique `users.account_id` in an expand migration. Preserve `users.id` as the
   internal primary and foreign-key root. Do not rewrite existing foreign keys.
2. During the bounded conversion period, resolve OAuth callbacks in this order:
   - match an existing non-null `account_id` first;
   - otherwise, when exactly one row matches the returned legacy profile `id` and its
     `account_id` is null, claim that row once by setting `account_id`;
   - when the two keys point to different rows, a key is duplicated, or the result is otherwise
     ambiguous, fail closed and require reviewed recovery; do not merge rows or create a
     replacement account automatically; and
   - create a new internal user only when neither identity key matches.
3. Keep the latest Spotify profile `id` as compatibility metadata during this decision's scope. It
   is not authoritative for account linking after the authority switch. Preserve the
   `spotify_user_id` storage and response fields until a separate accepted public-compatibility and
   retention decision changes them.
4. Before dual-key behavior is enabled for any live cohort, the implementation rollout plan must
   name a finite start and end, the initial active-user cohort, owner communication, monitoring,
   recovery, and rollback steps without recording PII in repository or tracker evidence.
5. Every active member of the initial one-to-five-user cohort must reauthorize and acquire an
   unambiguous `account_id` before the authority switch. Reaching the rollout end without satisfying
   that gate blocks the switch and returns the exception to the owner; it does not extend legacy
   linking indefinitely or discard a user.
6. After the completion gate, `account_id` is the sole key for new login and account linking.
   Disable the legacy-profile-ID fallback. Rows that were outside the active cohort may remain
   nullable and quarantined for later reviewed recovery; do not erase them merely to force a
   `NOT NULL` constraint.
7. Implement schema, OAuth, fixtures, rollout, monitoring, and recovery only through a separately
   reviewed plan and issue. This ADR grants no schema migration, production access, account access,
   OAuth-console mutation, deployment, or bulk-backfill authority.

## Consequences

- The migration reaches Spotify's supported identity model without rewriting the existing data
  graph or immediately breaking public `spotify_user_id` consumers.
- The initial cohort can migrate through normal reauthorization, and the completion gate makes the
  temporary compatibility path finite and measurable.
- Authentication temporarily carries more branching, concurrency, and recovery complexity.
- Identity conflicts become explicit login failures that need operator review. This is preferable
  to silently joining accounts or duplicating user data.
- Dormant or quarantined legacy rows may retain a null `account_id`; their retention and eventual
  disposition remain a separate privacy/data decision.
- Profile retention, OAuth scopes, Google email exchange, and public MCP/API compatibility are not
  resolved by this ADR.

## Validation

The implementation plan must include:

- expand-migration and rollback tests for the nullable unique column;
- a complete authentication decision table covering new users, already-migrated users, one-time
  legacy claims, missing keys, conflicting rows, duplicate keys, retries, and concurrent callbacks;
- proof that conflicts fail closed without row merge, replacement creation, or credential/data
  reassignment;
- reauthorization and cohort-completion evidence that contains no Spotify identifiers, tokens,
  email addresses, or other PII;
- explicit feature-switch tests for dual-key mode and `account_id`-only mode;
- proof that internal foreign keys and current public `spotify_user_id` response fields remain
  compatible; and
- a rehearsed authority-switch, rollback, and forward-recovery path before any production change.

## Rollback / revisit trigger

Before the authority switch, stop new `account_id` claims, retain the additive column and mappings,
and return to the reviewed legacy fallback only under the rollout plan. Do not drop the column or
discard acquired mappings merely to roll back application code.

After the authority switch, use a previous application revision only if evidence proves that no
new account or divergent mapping depends on `account_id`; otherwise use a reviewed forward repair.
Never resolve rollback by automatically merging users or deleting identity evidence.

Revisit this decision if Spotify changes or removes the `account_id` contract, representative
payloads omit it, uniqueness cannot be enforced, the active cohort cannot complete the bounded
reauthorization gate, or a later public-compatibility or retention decision changes the required
identity surface.

## Related decisions

- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) requires contract-first
  staged replacement and keeps authentication, data migration, and public compatibility plan-first.
- The SPM-5 audit's remaining OAuth/profile retention, public MCP/API, app-mode/quota, episode/embed,
  and Audio Features choices require their own accepted decisions before implementation.
