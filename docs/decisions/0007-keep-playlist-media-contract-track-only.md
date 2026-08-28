# ADR 0007 - Keep the playlist media contract track-only

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing explicit track-only handling, first-class episode support, and
silent filtering, Yuval Moran selected Option A and stated, "I've no current intention to use this
app for podcasts or anything else that has episodes" on 2026-08-27 UTC.

## Context

Spotify playlist items can be tracks or episodes. The official playlist endpoints currently use
tracks as the default item type and expose `additional_types` for clients that also support
episodes, while warning clients to discriminate future item types by each object's `type` field.
The current client does not request episodes, but its playlist-item model normalizes every returned
`item` into a track-shaped field before proving its type. An unexpected episode or future media
type can therefore fail validation or be coerced into an incomplete track-like object.

The MCP responses, Explorer cache, playlist-memory ledger, mutations, and operator documentation
all use track IDs and track metadata. Recently played history does not supply podcast episodes, and
the owner has no current episode or podcast product requirement. The supporting inventory is
recorded in the [SPM-5 Spotify Web API audit](../migration/spm-5-spotify-web-api-audit-2026-08-25.md).

## Decision drivers

- Match the initial music-history and playlist-memory product rather than inventing a podcast
  product.
- Prevent an unexpected Spotify item type from crashing or masquerading as a track.
- Preserve playlist position and incompleteness evidence instead of silently dropping items.
- Avoid a database migration and public track-or-episode union with no demonstrated user need.
- Keep track mutations, cache records, and playlist-memory reconstruction semantically honest.
- Retain a deliberate path to first-class episode support if a real product requirement appears.

## Options considered

### Keep an explicit track-only contract with safe placeholders

Continue to request only tracks, discriminate every returned item by type before validating track
fields, and map an unexpected episode or unknown media type into the existing unavailable-item
representation. This preserves ordering and exposes incompleteness without adding an episode
schema. Episode playback, metadata, persistence, and mutation remain unsupported.

### Add first-class episode support now

Introduce a track-or-episode union through the Spotify client, public MCP/API responses, Explorer,
cache persistence, playlist memory, mutation tools, and reconstruction. This models Spotify more
completely but creates a broad public and database migration for a feature the owner does not plan
to use.

### Drop unsupported items

Filter episodes and unknown item types out of playlist results. This keeps every result track-shaped
with little implementation work, but corrupts ordering and counts and can make a partial backfill
look complete.

## Decision

Keep the playlist media contract explicitly track-only.

1. Do not opt into episode playlist items. Keep `additional_types=episode` absent from playlist
   metadata and item requests unless this ADR is amended or superseded.
2. Discriminate the upstream `item.type` before validating a `SpotifyTrack`. Accept `track` through
   the existing track model. Treat `episode` and unknown future types as unsupported rather than
   coercing them into tracks.
3. Preserve an unsupported item's playlist position through the existing unavailable-item
   representation. Do not emit episode-specific fields or silently omit the item. The dedicated
   public MCP/API compatibility decision owns the exact stable outward envelope and warning text.
4. Keep `spotify.add_tracks`, `spotify.remove_tracks`, playlist-memory mutations, manual backfill,
   cache persistence, and reconstruction track-only. Reject an episode URI or non-track identifier
   locally before a Spotify request or database mutation.
5. Do not persist episode IDs, episode metadata, show metadata, playback positions, or derived
   track-like records in the current cache, ledger, or listening-history schema.
6. An unsupported placeholder is evidence of an incomplete track-only view, not a successful
   episode import. Counts, source information, and warnings must remain honest about that boundary.
7. First-class episode support requires a demonstrated product use case, a versioned public
   contract, a database and retention plan, and an accepted amendment or superseding ADR.
8. This decision records the target media boundary only. It authorizes no public-contract,
   database, production, provider-account, credential, deployment, or Spotify-data access change.

## Consequences

- The initial product stays aligned with its actual music-focused use case and avoids speculative
  podcast architecture.
- Unexpected episodes and future item types can no longer crash or silently become malformed
  tracks after the decision is implemented.
- Playlist order and missing-item evidence remain observable through unavailable placeholders.
- Users cannot import, inspect, mutate, analyze, or reconstruct episodes as first-class content.
- Mixed-media playlists can be incomplete from the product's perspective even when Spotify reports
  a larger total; the response must say so rather than claiming a complete track list.
- Adding episode support later remains a material, explicitly planned migration rather than a
  hidden widening of the current track contract.

## Validation

The implementation and rollout plans must include:

- raw Spotify fixtures for a track, an episode, an unavailable item, and an unknown future type;
- parser tests proving type discrimination occurs before `SpotifyTrack` validation;
- mixed-playlist tests proving unsupported items preserve their original positions and counts;
- request tests proving playlist reads do not opt into `additional_types=episode`;
- mutation tests proving episode and non-track URIs fail before Spotify request dispatch;
- cache and playlist-memory tests proving unsupported media does not create track records;
- public compatibility tests for the accepted unavailable-item envelope, count, and warning rules;
  and
- regressions proving normal track-only playlists retain their current schemas and behavior.

## Rollback / revisit trigger

Recording this ADR changes no runtime behavior. If a later implementation must be rolled back,
restore the previous parser while keeping episode opt-in disabled; do not drop, rewrite, or invent
playlist items in persisted memory as a rollback shortcut.

Revisit the decision if the owner adopts a podcast or episode feature, Spotify removes the
track-only compatibility behavior, episode placeholders become common enough to prevent useful
playlist operation, or an approved product requirement needs mixed-media playlist fidelity.

## Related decisions

- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) establishes the
  restricted Development common denominator and requires conservative handling of unsupported
  Spotify capabilities.
- [ADR 0006](0006-bundle-both-playlist-modification-scopes-for-write-access.md) governs the scopes
  for supported track-oriented playlist mutations.
- [ADR 0008](0008-stage-retirement-of-undocumented-playlist-embed-scraping.md) governs the separate
  source-of-data question for the unofficial embed fallback.
- [ADR 0010](0010-version-the-public-mcp-api-contract-before-correction.md) governs versioned
  response and error envelopes while keeping both versions track-only.
