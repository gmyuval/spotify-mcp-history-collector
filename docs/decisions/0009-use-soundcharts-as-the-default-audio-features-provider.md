# ADR 0009 - Use Soundcharts as the default Audio Features provider

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing an off-by-default Soundcharts opt-in, the current Spotify-first
fallback, and complete deferral of Audio Features, Yuval Moran selected a Soundcharts-default
policy on 2026-08-27 UTC: "I would like to have Soundcharts on by default and get the audio
features from there. If we need to re-work the connection to Soundcharts, that's perfectly fine
with me".

## Context

The product already has an optional `audio_features` table, a track-detail radar chart, a
collector enrichment phase, and provider adapters for Spotify and Soundcharts. The current runtime
enables enrichment by default but constructs a new Spotify-first provider each collector cycle.
Spotify Audio Features is not available on the restricted Development Mode common denominator
selected by [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md). A 403
only disables the current provider instance, so the next cycle attempts the unsupported path again.

Soundcharts supplies the required normalized track descriptors without receiving a Spotify user
token. Its current documented platform-ID request returns the Soundcharts UUID and song metadata,
including Audio Features, in one request. The repository instead performs a platform-ID lookup and
then calls `/song/{uuid}/spotify/audio-features`; that second path is absent from the current
Soundcharts OpenAPI document. The integration must therefore be treated as stale until a mocked
contract update and a separately authorized provider proof confirm the current response.

Soundcharts currently offers a limited free production allowance and paid monthly quotas. The
provider publishes usage through response headers and a no-charge quota endpoint. Exact price,
quota, endpoint inclusion, and terms are external facts that may change and must be revalidated
before purchase or activation. This ADR chooses the product and integration policy; it does not
purchase a plan, create an account, obtain credentials, contact the provider, or access real data.

## Decision drivers

- Make Audio Features a normal product capability rather than an indefinitely deferred experiment.
- Use one provider that works independently of Spotify app mode and user-token entitlement.
- Avoid unsupported Spotify requests and shared Spotify quota consumption.
- Keep provider cost measurable and bounded for the initial one-to-five-user deployment.
- Minimize the data disclosed to the external provider and keep feature values catalog-scoped.
- Preserve graceful operation when provider credentials, quota, or service availability is absent.
- Make missing and partial enrichment observable without treating absent values as zero.
- Provide provenance and freshness evidence for later calculated taste-profile work.

## Options considered

### Use Soundcharts as the default provider

Enable Audio Features as the normal target behavior and use Soundcharts as the sole default
provider. Correct the adapter to the current documented contract, monitor quota, and degrade only
enrichment when the provider is unavailable. This gives the intended capability across supported
Spotify app modes at a recurring provider cost and with an external dependency.

### Disable enrichment by default and make Soundcharts an explicit opt-in

Retain the provider seam while making no provider calls unless an operator explicitly enables it.
This has no default cost and fits a strict YAGNI posture, but it makes a desired capability absent
from the normal product and makes later activation easier to defer indefinitely.

### Keep Spotify first with Soundcharts fallback

Preserve the current provider order and make Spotify 403 disablement persistent. This can exploit
grandfathered Spotify access without Soundcharts cost, but it creates entitlement-dependent
behavior, consumes user-token quota, and contradicts the restricted Development Mode baseline.

### Remove or indefinitely defer Audio Features

Disable the job and remove the capability from the near-term product. This is the lowest-cost and
simplest runtime, but gives up the existing track visualization and a useful evidence source for
future taste and playlist work.

## Decision

Use Soundcharts as the default Audio Features provider.

1. Audio Features enrichment is enabled by default in the target product. Soundcharts is the sole
   default provider for every supported Spotify app mode. The supported path must not call Spotify
   Audio Features first, as fallback, or as an entitlement probe.
2. Replace the stale Soundcharts adapter through [SPM-18](https://linear.app/stratex/issue/SPM-18/operationalize-soundcharts-and-musicbrainz-enrichment).
   Use the current documented platform-ID contract that returns song metadata and Audio Features
   in one request per uncached track. Centralize the selected API version and response mapping;
   never silently invent or screen-scrape an undocumented replacement endpoint.
3. Keep `ENRICH_AUDIO_FEATURES_ENABLED` as the operator kill switch, defaulting to enabled. If
   Soundcharts credentials are absent or invalid, quota is exhausted, or the provider is down,
   core collection and API service remain healthy. Enrichment reports an explicit sanitized
   unavailable/deferred state and missing features remain absent.
4. A production environment intended to provide Audio Features must supply a qualifying
   Soundcharts allowance or subscription and credentials through the accepted secret-management
   path. Free allowance may be used for a bounded adapter proof. Account creation, subscription
   purchase or upgrade, credential access, and live-provider testing remain separate external
   actions requiring their own authority; the application must never purchase or upgrade a plan.
5. Send only the Spotify track identifier needed to resolve the catalog item. Do not send a user
   ID, `account_id`, legacy Spotify profile ID, access token, playlist name or ID, listening event,
   preference, or any other user-specific context to Soundcharts. Credentials must never enter
   logs, metrics, fixtures, issues, or repository files.
6. Persist only normalized feature values and the minimum provenance and retrieval evidence needed
   to identify Soundcharts and assess freshness. Feature rows are catalog-scoped, may remain while
   their track exists, and must follow the track's existing cascade deletion. Raw provider payloads
   are not durable product data; the provider cache remains bounded to 30 days unless fresh terms
   and measured behavior justify an accepted change.
7. A missing provider result is not a zero-valued feature vector. UI, API, and future taste-profile
   consumers must represent absence explicitly, tolerate partial fields, and expose an aggregate
   completeness measure before using Audio Features in ranking or calculated profiles.
8. Bound provider work by the existing per-cycle maximum and a configurable quota safety reserve.
   Consume current quota headers and the provider's no-charge quota endpoint where available.
   Defer unfinished work at the safety threshold or on quota exhaustion without losing its
   checkpoint. Never infer a reset time, overrun a purchased quota deliberately, or auto-upgrade.
9. Authorization failure disables provider calls persistently until configuration is deliberately
   reloaded or corrected. Rate limits and transient server failures receive bounded retries that
   honor valid provider guidance. Not-found results receive a bounded negative-cache interval so a
   track may be retried after the provider's documented population window without being queried on
   every collector cycle.
10. Treat provider cost as part of the application operating cost. Record actual request volume,
    cache effectiveness, coverage, and incremental monthly cost without track or user identifiers.
    Revalidate current plans and terms before activation and before every plan change.
11. Implement and deliver this policy only through reviewed issue work. This ADR authorizes the
    target and the SPM-18 adapter rework, but grants no provider-account, credential, real-track,
    subscription-spend, deployment, production, cloud, public-contract, or unrelated database
    migration authority.

## Consequences

- Audio Features have one app-mode-independent default source and no longer consume Spotify user
  tokens or shared Spotify quota.
- Production must carry a Soundcharts allowance or subscription to deliver the default capability;
  the incremental recurring provider cost can exceed the initial Azure infrastructure estimate.
- The application remains usable without Soundcharts, but operators and users can distinguish
  provider unavailability from a track that has no returned features.
- One documented provider request replaces the current two-step stale integration on cache miss,
  reducing quota use and simplifying failure handling.
- A provider outage, plan change, contract change, or quota exhaustion can delay enrichment without
  delaying playback-history collection or corrupting checkpoints.
- Catalog-scoped normalized data remains useful across users without exposing their listening
  histories to Soundcharts.
- SPM-18 must update adapter tests, provider selection, quota controls, readiness/operations
  evidence, and provenance handling before the target can be considered implemented.

## Validation

The implementation and rollout plans must include:

- contract fixtures for the current documented Soundcharts platform-ID response, including full,
  partial, missing, malformed, unauthorized, rate-limited, exhausted-quota, and server-error cases;
- tests proving the supported provider chain makes no Spotify Audio Features request in
  Development or Extended configurations;
- one-request-per-uncached-track and cache-hit tests, plus bounded negative-cache behavior;
- startup and run-loop tests proving missing/invalid credentials, quota exhaustion, and provider
  outages skip or defer enrichment without failing core collection;
- quota-reserve and checkpoint tests proving no automatic upgrade, deliberate overrun, lost work,
  or tight retry loop occurs;
- privacy tests proving outbound requests, logs, metrics, and errors contain no user-specific data,
  Spotify tokens, or provider credentials;
- persistence tests proving provider provenance/freshness is retained, raw payload caching is
  bounded, and feature rows follow track deletion;
- UI/API/taste-consumer tests proving missing or partial values are not converted to zeros and
  completeness is visible before ranking use;
- a bounded live-provider proof, only under separate authority, that confirms the documented
  endpoint, plan inclusion, returned scale and fields, quota accounting, and sanitized telemetry;
  and
- a pre-activation cost record using current provider pricing plus measured initial catalog size
  and cache-miss volume.

## Rollback / revisit trigger

Before provider activation, rollback is removal of the implementation commit with no provider or
data effect. After activation, set `ENRICH_AUDIO_FEATURES_ENABLED=false` or remove the credentials
to stop new calls while preserving already normalized feature rows and collection checkpoints.
Do not delete feature data or switch back to Spotify as an implicit rollback.

Revisit this decision if Soundcharts removes or materially changes the required fields, no
qualifying plan is economically reasonable, measured coverage or accuracy is insufficient, terms
prohibit the accepted storage/use, provider cost exceeds its approved budget, or a supported and
more appropriate source becomes available. Changing the default provider or retention boundary
requires an amendment or superseding ADR.

## Related decisions

- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) selects the small-cohort
  Azure target but does not authorize provider spend, secrets, deployment, or production changes.
- [ADR 0005](0005-support-spotify-development-mode-as-the-common-denominator.md) selects restricted
  Development Mode and establishes that Spotify Audio Features cannot be assumed available.
- [ADR 0007](0007-keep-playlist-media-contract-track-only.md) keeps persisted media track-only;
  Soundcharts enrichment applies only to supported tracks.
- [SPM-18](https://linear.app/stratex/issue/SPM-18/operationalize-soundcharts-and-musicbrainz-enrichment)
  owns operational provider implementation after SPM-5 resolves this policy.
- [SPM-16](https://linear.app/stratex/issue/SPM-16/build-a-deterministic-provenance-aware-calculated-taste-profile)
  may consume the normalized values only with completeness and provenance evidence.
