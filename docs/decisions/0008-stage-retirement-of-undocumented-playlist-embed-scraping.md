# ADR 0008 - Stage retirement of undocumented playlist embed scraping

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing staged retirement, indefinite best-effort retention, and immediate
retirement of the unofficial playlist embed fallback, Yuval Moran selected staged retirement with
"Decision 2 - A" on 2026-08-27 UTC.

Amendment evidence: after reviewing the privacy risk of private, unknown, or stale-cached playlist
visibility, Yuval Moran approved the exact amendment-and-fix package with "I do" on 2026-08-27 UTC.
The fallback remains staged compatibility debt, but current official metadata must prove public
visibility before each outbound embed request.

## Context

Spotify now documents `GET /playlists/{id}/items` as available only when the authenticated user
owns or collaborates on the playlist. The application currently tries official metadata and item
paths first, then can fetch `open.spotify.com/embed/playlist/{id}` and parse a private
`__NEXT_DATA__` structure when official content access returns 403. Spotify documents Embeds and
oEmbed for displaying content and basic link metadata, not as an ordered playlist-item API.

The fallback supports a real current workflow: importing non-owned public reference playlists into
playlist memory. It is nevertheless layout-dependent, partial for larger playlists, and outside a
documented data contract. Spotify's current Developer Terms also restrict automated retrieval or
indexing of Spotify Service content, expressly including playlist data, which creates material
policy uncertainty even though this ADR makes no legal determination.

Immediate removal would break demonstrated personal use and leave impractical manual entry for
large playlists. Indefinite retention would make a brittle hidden HTML structure part of the target
architecture. The supporting code and contract inventory is recorded in the
[SPM-5 Spotify Web API audit](../migration/spm-5-spotify-web-api-audit-2026-08-25.md).

## Decision drivers

- Preserve an actual initial-user workflow long enough to replace it safely.
- Make official Spotify APIs the only permanent automated playlist-data source.
- Avoid presenting private page structure as a supported Spotify contract.
- Measure whether the fallback is still used without logging playlist IDs, user IDs, or content.
- Give operators an immediate kill switch if Spotify behavior or policy requires shutdown.
- Provide a practical user-supplied import path before removing automated non-owned backfill.
- Keep retirement evidence-based and owner-approved rather than allowing "temporary" to become
  indefinite.

## Options considered

### Stage retirement with a migration path

Classify the embed parser as transitional compatibility debt, put it behind a kill switch, measure
privacy-safe aggregate outcomes, add a user-provided URI/list import path, and retire the parser
after an owner-approved usage and migration gate. This preserves the demonstrated workflow during
migration without promising the private structure as target architecture.

### Retain it indefinitely as best-effort support

Continue the hidden-data fallback with partial-result warnings. This maximizes current convenience
and minimizes immediate work, but permanently depends on undocumented layout and unresolved policy
risk for data written into persistent playlist memory.

### Retire it immediately

Remove embed fetching and allow only official access to owned or collaborative playlists plus
current manual backfill. This reaches the clean boundary fastest but abruptly removes a real
workflow before a usable replacement exists.

## Decision

Stage retirement of undocumented playlist embed scraping.

1. Treat `SpotifyEmbedClient` and its `__NEXT_DATA__` parser as transitional compatibility debt,
   not a supported target-architecture integration or evidence of an official Spotify contract.
2. Keep the existing fallback available only during a bounded migration. Do not add new embed
   data fields, new hidden paths beyond repairs required to preserve the existing bounded behavior,
   or new product features that depend on scraped data.
3. Add an operator-controlled kill switch that disables outbound embed retrieval without a deploy.
   Disabled behavior must fail closed to the accepted restricted/manual-import path.
4. Add privacy-safe observability for aggregate attempt, success, partial, failure, and disabled
   outcomes. Do not log or label metrics with user IDs, playlist IDs, playlist names, track IDs,
   Spotify account data, or content metadata.
5. Continue to prefer the official Spotify API. The fallback may run only after the accepted
   official-access failure conditions and only when official metadata obtained during the current
   request reports `public: true`. Private, null, unknown, failed, or cached-only visibility cannot
   authorize an embed request and must fail closed to the restricted/manual-import path. Keep the
   bounded fallback initially enabled behind its planned operator kill switch; this amendment does
   not invent a separate compliance-approval mechanism or default it off before the replacement is
   ready. Eligible fallback results remain explicitly best-effort and partial-capable.
6. Before retirement, provide the smallest practical user-supplied track URI/list import path for
   non-owned reference playlists. Its public schema, validation, privacy, and persistence behavior
   require their own accepted plan and Linear delivery work before implementation.
7. Default the future Azure environment to the official path once the replacement import is
   verified. This ADR does not authorize Azure resource creation, configuration, deployment, or
   production cutover.
8. Retire the parser only after the replacement is validated, aggregate usage evidence is reviewed,
   and the owner explicitly approves the retirement gate. Record that decision in an amendment or
   superseding ADR; do not infer approval from elapsed time or low traffic.
9. [ADR 0010](0010-version-the-public-mcp-api-contract-before-correction.md) freezes v1
   `tracks_source="embed"` compatibility and gives v2 a source-neutral transitional fidelity
   contract. Actual parser retirement and any claim that the transitional source is unreachable
   still require this ADR's replacement evidence and explicit owner gate.
10. This decision grants no production, provider-account, credential, real-playlist, cloud,
    deployment, public-contract, or data-migration authority.

## Consequences

- Existing users retain a temporary route for non-owned public playlist backfill while a practical
  import replacement is prepared.
- The target architecture no longer depends on private Spotify page structure.
- Temporary code, tests, documentation, and operational support remain until the explicit
  retirement gate is accepted.
- Aggregate metrics and a kill switch add small implementation and operational cost.
- The fallback can still break or return partial data during migration; its output must never be
  described as complete solely because parsing succeeded.
- Some genuinely public playlists require manual import when current official metadata cannot
  prove their visibility; stale cached visibility is deliberately insufficient.
- After retirement, automatic content retrieval is limited to Spotify's supported ownership and
  collaboration boundary; non-owned reference playlists require user-supplied input.

## Validation

The implementation and rollout plans must include:

- kill-switch tests proving disabled mode makes no request to `open.spotify.com`;
- official-first tests proving embed retrieval never precedes or replaces an eligible official API
  request;
- negative tests proving private, null, unknown, metadata-failed, and cached-only visibility make
  no outbound embed request;
- aggregate observability tests proving every outcome is counted without sensitive labels or log
  fields;
- partial-result and parser-failure tests proving incomplete data cannot be reported as complete;
- manual URI/list import contract, validation, ordering, duplicate, maximum-size, and privacy tests;
- current-user migration evidence showing the replacement can handle demonstrated large reference
  playlists before retirement;
- a documented owner review packet containing aggregate usage, replacement readiness, public
  compatibility impact, and rollback posture; and
- post-retirement tests proving the parser and outbound embed calls are absent after an accepted
  amendment or superseding decision.

## Rollback / revisit trigger

The original acceptance of this ADR changed no runtime behavior. The 2026-08-27 amendment and its
reviewed implementation now fail closed unless current official metadata proves `public: true`.
Rolling that privacy gate back requires another accepted amendment; cached or unknown visibility
must not silently regain authority. Before the parser is retired, rollback of a kill switch,
metrics, or replacement-import implementation may otherwise restore the preceding application
revision without changing Spotify accounts or persisted playlist memory. After retirement, do not
silently restore scraping; a rollback that re-enables embed retrieval requires the same explicit
owner gate and policy review as retirement.

Revisit the staged approach if Spotify publishes a supported ordered playlist-content API for
non-owned public playlists, formally documents an Embed data interface that satisfies this use
case, requires immediate cessation, the hidden structure stops working, or the owner decides the
remaining workflow does not justify the migration period.

## Related decisions

- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) selects Spotify
  Development Mode as the common denominator and excludes unsupported access assumptions.
- [ADR 0007](0007-keep-playlist-media-contract-track-only.md) keeps the media model track-only
  regardless of whether a playlist item comes from an official or transitional source.
- [ADR 0010](0010-version-the-public-mcp-api-contract-before-correction.md) governs versioning of
  embed-visible fields, warnings, and failure behavior while preserving this ADR's parser-retirement
  gate.
- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) governs Azure migration and
  does not receive deployment authority from this record.
