# SPM-5 Spotify Web API audit - 2026-08-25 UTC

This dated audit inventories the Spotify contracts used by the repository and compares them with
Spotify-owned documentation current through August 2026. It contains no credential, app-console,
allowlist, account, token, production, database, or personal-data inspection.

Evidence labels:

- **Measured** - observed in `origin/main` revision
  `137dd54f0a82b21759ce3e9bb506204314f202a8` or a linked official Spotify source.
- **Inferred** - a consequence of measured evidence that still needs a named decision or test.
- **Unresolved** - Spotify does not publish the fact, official sources conflict, or live account
  access was intentionally outside scope.

## Official source set

Sources were retrieved on 2026-08-25 UTC:

- [February 2026 platform-security update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
- [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [February 2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)
- [March 2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/march-2026)
- [May 2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/may-2026)
- [July 2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/july-2026)
- [July 2026 quota update](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates)
- [Quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits)
- [Scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes)
- [Current user profile](https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile)
- [Search](https://developer.spotify.com/documentation/web-api/reference/search)
- [Recently Played](https://developer.spotify.com/documentation/web-api/reference/get-recently-played)
- [Playlist Items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items)
- [Add Items](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist)
- [Remove Items](https://developer.spotify.com/documentation/web-api/reference/remove-items-playlist)
- [November 2024 Audio Features change](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)
- [Single Audio Features reference](https://developer.spotify.com/documentation/web-api/reference/get-audio-features)
- [Batch Audio Features reference](https://developer.spotify.com/documentation/web-api/reference/get-several-audio-features)

Official material has unresolved conflicts:

1. The updated February announcement postpones endpoint-access changes for existing Development
   integrations, while the migration guide says existing integrations changed on March 9.
2. The migration guide describes grandfathering above five users, while current quota-mode prose
   and the updated announcement describe a five-user cap.
3. Official prose establishes that the app owner needs Premium; it does not establish that every
   allowlisted user needs Premium.
4. Spotify does not publish the numeric Development quota, reset timing/grouping details, or a
   guaranteed `Retry-After` value for `QUOTA_EXCEEDED`.
5. Some current reference pages retain legacy playlist/field entries as deprecated while the
   changelog calls them removed for affected Development access.

Do not infer this installation's app age, quota mode, owner plan, allowlist, grandfathering, or
developer-account grouping from those documents.

## Endpoint inventory

All `/v1` requests use `services/shared/src/shared/spotify/client.py` unless a different owner is
named.

| Method and path | Repository consumer and contract | August 2026 classification |
|---|---|---|
| Browser `GET accounts.spotify.com/authorize` | `services/api/src/app/auth/service.py`; code, redirect URI, state, eight scopes, optional dialog. | Grant shape remains current. Scope policy has decision blockers below. |
| `POST accounts.spotify.com/api/token`, authorization-code grant | `auth/service.py`; access token, type, expiry, optional refresh token and scope. | Grant shape remains current. Generic HTTP error handling only. |
| Same token endpoint, refresh grant | Independent API and collector implementations in `auth/tokens.py` and `collector/tokens.py`. | API persists rotated refresh token and scope; collector persists rotated refresh token but not returned scope. No quota-reason handling. |
| `GET /me` | Direct auth call; persists `id`, display name, email, country, and product. | `account_id` is ignored. Email/country/product are unavailable to affected Development access. [ADR 0003](../decisions/0003-adopt-staged-account-id-migration.md) accepts a bounded additive identity migration; implementation remains plan-first. |
| `GET /me/player/recently-played` | Polling and initial sync; limit 50 and cursor paging. | Current and compliant; no podcast episodes are returned. |
| `GET /tracks?ids=` | Batch client method; no non-test production consumer found. | Removed for affected/new Development access; available to Extended and possibly postponed existing integrations. Do not remove until the supported-mode decision. |
| `GET /artists?ids=` | Batch client method; no non-test production consumer found. | Same mode qualification as batch tracks. |
| `GET /audio-features?ids=` | Spotify-first collector enrichment. | Deprecated and unavailable to affected/new Development access; existing Extended integrations were declared unaffected. |
| `GET /me/top/artists` | `spotify.get_top` MCP handler. | Current. Removed fields remain optional locally. |
| `GET /me/top/tracks` | `spotify.get_top` MCP handler. | Current. Removed fields remain optional locally. |
| `GET /search` | MCP search and collector resolver. | Current range is 0-10 and default is 5. ADR 0010 freezes that v1 behavior and accepts a corrected v2 range of 1-10 with default 5; implementation and client migration remain plan-first. |
| `GET /tracks/{id}` | MCP and Explorer track detail. | Current. Popularity can be absent under affected Development access. |
| `GET /artists/{id}` | MCP and Explorer artist detail. | Current. Genres, popularity, and followers can be absent under affected Development access. |
| `GET /albums/{id}` | MCP and Explorer album detail. | Current. Label and popularity can be absent under affected Development access. |
| `GET /me/playlists` | MCP returns one caller-sized page; Explorer exhausts pages. | Current. Private/collaborative scopes apply. |
| `GET /playlists/{id}` | Metadata plus canonical/legacy embedded-item compatibility. | Current for metadata. Contents are separately authorized. |
| `GET /playlists/{id}/items` | MCP and Explorer; max page 50, follows `next`, offset fallback, duplicate-page guard. | Current path. Contents return 403 unless the user owns or collaborates on the playlist. Item can be track or episode. |
| `POST /me/playlists` | MCP create playlist. | Current. |
| `POST /playlists/{id}/items` | MCP add, max 100, snapshot response. | Current path. Track or episode URIs are accepted upstream. |
| `DELETE /playlists/{id}/items` | MCP remove, max 100, snapshot response; no optional `snapshot_id` precondition. | Current path. Adding the precondition is optional maintenance, not required for compliance. |
| `PUT /playlists/{id}` | MCP playlist detail update. | Current. |
| Unofficial `GET open.spotify.com/embed/playlist/{id}` | `shared/spotify/embed.py`; parses private `__NEXT_DATA__`, rate-limits and retries. | Not a documented Web API contract. ADR 0008 accepts staged retirement; current-public authorization is enforced now, while the kill switch, replacement import, evidence, and final owner retirement gate remain future reviewed work. |

No currently-playing, playback-state, device, queue, or corresponding OAuth-scope use exists.

## Model and field inventory

The Spotify payload model surface is concentrated in
`services/shared/src/shared/spotify/models.py`:

- Image: URL and nullable dimensions.
- Simplified/full artist: ID, name, URI/href/URLs; full model adds genres, popularity, images,
  followers.
- Simplified/full album: ID, name, URI, type, release date, images/URLs; full model adds genres,
  popularity, label, track totals/items, artists, and copyrights.
- Track: ID, name, URI, duration, explicit, popularity, track/disc numbers, local flag, artists,
  album, external IDs/URLs, preview URL, and href.
- Playback history: track, timestamp, context type/URI/href/URLs, before/after cursors, page fields.
- Batch wrappers: nullable tracks, artists, and audio features.
- Audio Features: the twelve stored feature values plus ID/URI/duration.
- Top and Search paging: items, totals, limit/offset, and relevant resource sections.
- Playlist: owner, images, visibility/collaboration, canonical `items/item` and legacy
  `tracks/track`, snapshots, paging, URLs, added time/user, and mutation snapshot response.
- Embed: extracted track ID, title, artist subtitle, duration, and unavailable flag.
- OAuth profile/token models in `services/api/src/app/auth/schemas.py` ignore `account_id` and retain
  `id`, display name, email, country, and product.

Persistence in `services/shared/src/shared/db/operations.py` consumes Spotify track ID/name/duration,
album ID/name, ISRC, artist ID/name, play time, and context type/URI. The March changelog reversed
the planned `external_ids` removal, so current ISRC persistence remains valid.

Confirmed February-removed response fields are optional in local Pydantic models, so absence does
not itself break parsing. MCP and Explorer still expose nullable popularity, genre, follower, label,
email, country, and product fields. Removing/versioning those keys is a public-contract decision.

Playlist `item` is track-or-episode upstream, while the local model is track-only. An episode can
fail validation or be coerced into an incomplete track-like shape depending on its payload. A new
episode result type would change MCP/API/cache contracts and requires an accepted decision.

## OAuth scope inventory

Configured scopes in `services/api/src/app/constants.py`:

| Scope | Current dependency |
|---|---|
| `user-read-recently-played` | Polling and initial sync. |
| `user-top-read` | Top artists and tracks. |
| `user-read-email` | Currently persists `/me` email and supports the email-to-user Google exchange. [ADR 0004](../decisions/0004-separate-provider-identities-and-minimize-profile-retention.md) selects removal after every active user has an explicit stable Google provider link. |
| `user-read-private` | Currently persists country/product and is listed by the current Search reference. ADR 0004 stops profile-field retention but retains this scope only while an accepted Search contract requires it. |
| `playlist-read-private` | Private playlists and local 403 diagnosis. |
| `playlist-read-collaborative` | Collaborative playlists in the current-user list. |
| `playlist-modify-public` | Public playlist mutations. |
| `playlist-modify-private` | Private playlist mutations. |

[ADR 0006](../decisions/0006-bundle-both-playlist-modification-scopes-for-write-access.md)
accepts the current complete-bundle policy: every initial write-enabled user grants both
modification scopes, and every playlist mutation fails locally if either is absent. This avoids a
metadata request or undocumented visibility rule while preserving the complete public-and-private
feature set. The bundle is not proof of ownership or other resource authority. It formalizes
current behavior and authorizes no OAuth rollout, provider/account access, or public-contract
change.

## Rate-limit and quota audit

Before this branch, `SpotifyClient` retried every 429 as a rolling 30-second-window limit, trusted
`float(Retry-After)`, discarded `error.reason`, and eventually raised `SpotifyRateLimitError`.
Development quota exhaustion therefore retried pointlessly and was mislabeled; a malformed header
escaped as `ValueError`.

This branch adds only compatibility-preserving internal maintenance:

- `reason=QUOTA_EXCEEDED` raises `SpotifyQuotaExceededError`, a
  `SpotifyRateLimitError` subtype, without retrying. Existing outward handlers therefore retain
  their current rate-limit classification.
- A malformed `Retry-After` falls back to existing exponential backoff rather than escaping.
- No numeric quota, reset time, quota-specific delay, or shared request budget is invented.

The complete repository retry inventory is:

- `SpotifyClient` defaults to three retries, so ordinary 429 and 5xx responses receive at most
  four attempts. Its fallback delay is `1.0 * 2**attempt` seconds; valid `Retry-After` values replace
  that delay for 429 responses. A 401 can invoke the token-refresh callback once, other 4xx
  responses fail immediately, and transport-level `httpx` exceptions are not retried.
- The unofficial embed client also defaults to three retries/four attempts. It retries transport
  errors, 429, and 5xx responses; honors a numeric non-negative `Retry-After` for 429; otherwise
  uses exponential delay plus random 0-to-0.5-second jitter. A lock serializes requests and a
  two-second minimum interval applies before a fetch. Other non-200 responses fail immediately.
- OAuth code exchange and `/me` profile fetch each make one request with no retry; their response
  helper classifies status codes only.
- API and collector token refresh each make one POST with no retry. The API raises typed
  `TokenRefreshError` and persists returned scope plus a rotated refresh token. The collector raises
  `RuntimeError` and persists a rotated refresh token, but not returned scope.

[ADR 0005](../decisions/0005-support-spotify-development-mode-as-the-common-denominator.md)
selects the current restricted Development surface as the common denominator for the initial
one-to-five-user product. Extended installations run the same path, while postponed legacy access
and Extended-only endpoints are not supported contracts. It keeps `QUOTA_EXCEEDED` terminal for the
current operation and requires coordinated caching, coalescing, foreground priority, jittered and
resumable background deferral, and sanitized developer-budget observability before release. It does
not authorize implementation or change the outward MCP/API rate-limit shape.

## Search maintenance and public boundary

The official Search contract now defaults to 5 and accepts `limit` from 0 through 10. The shared
client still defaults to 20 and passes caller values such as 50 through unchanged. The MCP catalog
advertises 1-50 with default 10, and the handler accepts 50. RED observations recorded each mismatch.

An attempted shared-client correction was deliberately removed before delivery because changing
that client would change public MCP behavior indirectly. Resolve the shared and MCP contracts
together through [ADR 0010](../decisions/0010-version-the-public-mcp-api-contract-before-correction.md):
freeze the current Action and native MCP behavior as v1, introduce corrected explicit v2 endpoints,
migrate every known consumer, and retire v1 only after the accepted evidence and owner gates. ADR
0003 remains limited to the `account_id` identity migration.

## Playlist audit

- Current code already uses `/items` for content and mutations and supports canonical `item` plus
  legacy `track` response shapes.
- Content pagination honors Spotify's current maximum 50, absolute `next`, a manual-offset fallback,
  duplicate-page protection, and a 10,000-item local safety cap.
- Non-owned/non-collaborative contents receive 403 under the current official contract. The embed
  fallback is unofficial and layout-dependent; this branch now requires current official metadata
  to prove `public: true` before making an outbound embed request.
- `playlist_tools.py` still emits a public warning that Development Mode limits retrieval to about
  100 items. Current official behavior is ownership/collaboration authorization, not a documented
  100-item cap. Correcting that public MCP text is grouped with the compatibility ADR rather than
  silently changed here.
- Playlist IDs, owner metadata, snapshots, item counts, added time, track metadata, and unavailable
  placeholders flow into the cache and memory-ledger surfaces. Episode support must include those
  consumers in its decision.

## Audio Features and external fallback

`AudioFeaturesEnrichmentService` currently enables enrichment by default, creates a Spotify-first
provider on every cycle, and optionally reuses a Soundcharts provider when both paid-provider
credentials exist. A Spotify 403 disables only that cycle's provider instance; the next cycle tries
Spotify again. Soundcharts resolves a Spotify ID, fetches provider features, caches them, and
disables on provider authorization failure. MusicBrainz is metadata enrichment, not an Audio
Features fallback.

Fresh Soundcharts documentation reviewed on 2026-08-27 returns the Soundcharts UUID, song metadata,
and Audio Features through the versioned platform-ID request. The repository's second
`/song/{uuid}/spotify/audio-features` path is absent from the current provider OpenAPI document, so
the existing adapter is stale until SPM-18 updates and verifies its contract. This is documentation
evidence, not a live-provider or credential probe.

This branch documents the actual environment settings and adds a test using the concrete Spotify
and Soundcharts provider adapters: a Spotify 403 falls through and returns Soundcharts features.
It does not change provider order, defaults, credentials, paid calls, cache policy, or production
behaviour.

ADR 0009 now selects Soundcharts as the sole default Audio Features provider and removes Spotify
Audio Features from the supported target chain. SPM-18 owns the separately reviewed adapter,
credential/privacy, quota/cost, cache/retention, degradation, and rollout implementation. Spotify
publishes no replacement or sunset date, but that no longer leaves the provider/default policy open.

## `account_id` identity impact

- `users.spotify_user_id` is unique and non-null; OAuth lookup, insert, and callback output use
  profile `id`.
- Internal integer `users.id` is the foreign-key root for tokens, plays, sync checkpoints, jobs,
  imports, RBAC, API tokens, caches, profiles, preference events, memory playlists/events, and logs.
- ZIP import attaches to an existing internal user ID. Export usernames are not identity joins.
- Official May guidance calls `account_id` public, pseudoanonymous, immutable, and the account-linking
  key, and explicitly says not to use `id` for linking.

No observed user is claimed to have changed `id`. The verified defect is reliance on a field the
official contract says not to use for account linking.

[ADR 0003](../decisions/0003-adopt-staged-account-id-migration.md) accepts a bounded staged
additive migration: preserve internal `users.id`, add a nullable unique `account_id`, claim exactly
one unambiguous legacy row during reauthorization, fail closed on every conflict, and make
`account_id` authoritative only after the complete initial active-user cohort passes a finite
rollout gate. It preserves `spotify_user_id` storage and current public response fields as
transitional runtime compatibility; ADR 0004 and ADR 0010 govern their separately reviewed
contraction and version migration. No schema, OAuth behavior, production account, or user data was
changed by the audit or ADR.

[ADR 0004](../decisions/0004-separate-provider-identities-and-minimize-profile-retention.md)
separates the Google provider subject from the Spotify identity and internal user, prohibits
email-only or single-user automatic linking, selects removal of `user-read-email` after the active
cohort is explicitly linked, and stops ingesting Spotify email, country, and product. Existing
values remain frozen until the public-nullability, rollback, cohort, and separately authorized
contraction gates pass.

[ADR 0005](../decisions/0005-support-spotify-development-mode-as-the-common-denominator.md)
accepts restricted Development Mode as the common denominator, treats the unused batch track and
artist methods as outside the target supported surface, and keeps Extended-only or postponed legacy
access out of the product contract. Batch-method retirement and quota coordination remain reviewed
implementation work; ADR 0009 and SPM-18 now govern the Audio Features provider and implementation.

[ADR 0007](../decisions/0007-keep-playlist-media-contract-track-only.md) accepts an explicit
track-only media boundary: playlist requests do not opt into episodes, and unexpected episodes or
future types preserve position as unsupported placeholders rather than becoming tracks or
disappearing. [ADR 0008](../decisions/0008-stage-retirement-of-undocumented-playlist-embed-scraping.md)
accepts staged retirement of the private embed parser after a kill switch, privacy-safe aggregate
evidence, a usable user-supplied URI/list import, and a later explicit owner gate. ADR 0007 remains
unimplemented here; ADR 0008's amended current-public proof is implemented as a compatible privacy
repair, while the kill switch, replacement import, and retirement gate remain future reviewed work.

[ADR 0009](../decisions/0009-use-soundcharts-as-the-default-audio-features-provider.md)
accepts Soundcharts as the sole default Audio Features provider, requires removal of Spotify from
the supported provider chain, and sends only a Spotify track identifier to the external provider.
The application must degrade only enrichment when credentials, quota, or provider availability is
missing. SPM-18 owns the current-contract adapter, bounded quota/cost controls, provenance, and
separately authorized live proof; this decision does not purchase, activate, or access Soundcharts.

## Delivered safe maintenance

- Non-retrying internal `QUOTA_EXCEEDED` classification that preserves the existing outward
  rate-limit base type, with focused RED and GREEN tests.
- Defensive malformed `Retry-After` fallback, with focused RED and GREEN tests.
- Concrete Spotify-403-to-Soundcharts fallback coverage without changing provider policy.
- Current-request `public: true` authorization for the transitional embed fallback, with private,
  null, metadata-failed, and cached-only paths failing closed.
- Removal of raw MCP arguments and playlist/embed identifiers from ordinary application logs,
  including suppression of `httpx` INFO request URLs at the API logging boundary.
- Current Development/Extended user-limit operator guidance, correction of internal import user ID,
  and documented audio-enrichment environment settings.

## Plan-first decision boundary

This audit records measured gaps and decision boundaries; it is not a work queue. Linear SPM-5 is
the sole tracker for their disposition. ADR 0003 accepts the staged `account_id` identity target,
ADR 0004 accepts provider-identity separation and minimized profile retention, ADR 0005 accepts the
restricted Development common denominator and internal quota-policy target, and ADR 0006 accepts
the complete playlist-write scope bundle. ADR 0007 accepts the track-only media boundary, and ADR
0008 accepts staged embed retirement. ADR 0009 accepts the Soundcharts-default Audio Features
target. ADR 0010 accepts a frozen-v1, corrected-v2, migrate-then-retire public compatibility target.
SPM-18 implementation still requires its separately reviewed plan and applicable authority,
including separate approval for provider-account access, credentials, subscription spend,
live-provider proof, deployment, or production mutation.

Apart from the compatible quota and privacy repairs listed above, no behavior change is authorized
by this audit for public MCP/API defaults and shapes, app-mode or quota-policy implementation,
playlist-scope or playlist-media implementation, unofficial-embed retirement, batch endpoint
retirement, or current runtime Audio Features behavior. ADR 0010 records the accepted
public-contract target; implementation, real-client migration, and v1 removal remain behind their
applicable plan-first and authority gates recorded through Linear. The ADR index assigns 0010 to
the accepted public-contract versioning policy and reserves 0011 next.

## Validation boundary

The audit can validate repository behavior with mocked official payloads and no Spotify access.
Live app mode, age, owner Premium, allowlist, quota pool, tokens, users, data, and provider consoles
remain intentionally unresolved. Tests and documentation are not evidence that production has a
particular quota mode or entitlement.
