# ADR 0005 - Support Spotify Development Mode as the common denominator

Date: 2026-08-27 (UTC)
Status: Accepted
Decision owners: Yuval Moran
Linear issue: [SPM-5](https://linear.app/stratex/issue/SPM-5/audit-and-update-for-spotify-web-api-changes-through-august-2026)
Owner evidence: after reviewing a Development-common-denominator baseline, mode-aware capability
tiers, and an Extended-first product, Yuval Moran selected the Development-common-denominator
option with "A" on 2026-08-27 UTC.

## Context

The initial product is a personal-and-friends system for one to five named users. Spotify's current
Development Mode requires a Premium app owner and permits up to five allowlisted authenticated
users. Extended Quota Mode removes that user cap and receives a higher quota, but current
eligibility is organization-focused and requires a launched service with a much larger audience.
Spotify also applies Development quota across Client IDs owned by the same developer and does not
publish a numeric quota, reset time, stable bucket grouping, or a guaranteed reset signal for
`QUOTA_EXCEEDED`.

Official 2026 material conflicts about which postponed legacy endpoints remain available to older
Development integrations. The repository cannot safely treat that temporary access as a product
contract. The SPM-5 audit found that the affected batch track and artist endpoints have no
non-test production consumer. Other surfaces, including public Search behavior, playlist
modification scopes, episode/embed behavior, and Audio Features, have independent compatibility or
provider consequences and are not decided by the app-mode choice.

The branch already classifies `reason=QUOTA_EXCEEDED` as a non-retrying internal subtype while
preserving the existing outward rate-limit type. It does not yet coordinate the developer-wide
budget, prioritize interactive requests over background collection, or persist background work for
later resumption. This ADR chooses the operating target; it does not implement those mechanisms.

## Decision drivers

- Fit the supported product to the actual one-to-five-user launch rather than hypothetical scale.
- Keep one behaviorally consistent product path across Development and Extended installations.
- Avoid depending on postponed, grandfathered, or Extended-only capabilities.
- Protect interactive MCP/API work when background collection shares the same external budget.
- Never turn an unpublished Spotify limit into a fabricated quota or reset promise.
- Keep public errors and remaining OAuth/provider choices behind their own compatibility decisions.
- Preserve a clear upgrade path if the audience or Spotify's eligibility rules materially change.

## Options considered

### Use Development Mode as the common denominator

Support the restricted Development endpoint and field surface for the initial product. Extended
installations may run the same path, but the product does not require or advertise Extended-only
behavior. This is the simplest contract for the initial cohort and avoids accidental reliance on
temporary access. It forgoes useful legacy or Extended-only capabilities until a real requirement
justifies them and requires careful request budgeting because Development quota is lower.

### Add explicit capability tiers for Development, postponed legacy access, and Extended Mode

Probe or configure a mode matrix and expose more capability where available. This can preserve
legacy behavior and exploit Extended access sooner. It multiplies test, support, documentation,
and failure paths around entitlements the application cannot reliably infer, and it creates
multiple product contracts before the initial cohort needs them.

### Make Extended Mode the product baseline

Design around the broadest endpoint surface and require Extended eligibility. This produces a
clean high-capability target and a higher quota ceiling. It is unavailable to the intended initial
personal-and-friends deployment, would make launch depend on organization and audience criteria,
and would optimize for scale the product does not yet have.

## Decision

Select Development Mode as the common denominator.

1. The initial supported operating shape is current restricted Development Mode for one to five
   named, allowlisted users. Operator documentation must state the Premium-owner and allowlist
   requirements without asserting that every allowlisted user needs Premium.
2. The supported core path may depend only on endpoints and response fields confirmed for current
   restricted Development access. Extended installations remain compatible by running that same
   path; Extended Mode is neither required nor advertised as a separate feature tier.
3. Postponed endpoint access available to an older Development integration is an observed temporary
   capability, not a default or durable contract. Do not introduce a speculative app-mode setting,
   entitlement probe, or mode matrix for the initial release.
4. The unused batch `GET /tracks?ids=` and `GET /artists?ids=` methods are outside the target
   supported surface. Their retirement, including test and caller proof, belongs to separately
   reviewed implementation work. Do not replace them speculatively where no production caller
   exists.
5. Spotify Audio Features remains governed by its dedicated provider/default decision. This ADR
   establishes only that the restricted Development baseline cannot assume Spotify Audio Features
   is available.
6. `reason=QUOTA_EXCEEDED` is terminal for the current Spotify operation and must not enter ordinary
   rolling-rate-limit retries or exponential backoff. No implementation may invent a quota number,
   reset time, quota-specific sleep, stable bucket grouping, or `Retry-After` guarantee.
7. Treat all Development Client IDs owned by the same Spotify developer as sharing one external
   budget. The implementation plan must name the ownership/configuration boundary and provide
   request coalescing and caching, jittered background scheduling, foreground-over-background
   priority, sanitized metrics, and resumable checkpoints. On quota exhaustion, background work
   defers without losing its checkpoint; foreground work receives the current compatible error.
8. Keep the existing outward MCP/API rate-limit compatibility until a dedicated public-contract
   decision accepts a new error shape. This ADR does not change Search defaults or limits, public
   warning text, response schemas, or client retry instructions.
9. Reassess Extended support only when more than five active users are required, the product meets
   Spotify's then-current eligibility criteria, or a validated near-term feature cannot be delivered
   on the common-denominator surface. Reassessment must use fresh official documentation and live
   entitlement evidence obtained under separate authority.
10. Implement this target only through reviewed issue work and the applicable plan-first gates.
    This ADR grants no Spotify dashboard/account access, allowlist or owner-plan mutation, credential
    access, public-contract change, OAuth-scope change, deployment, or production mutation.

## Consequences

- The launch contract matches the actual small cohort and avoids an unnecessary mode matrix.
- Development and Extended installations share one tested product path, reducing conditional
  behavior and support ambiguity.
- The product gives up postponed legacy and Extended-only endpoints until a concrete requirement
  and eligibility justify them.
- Lower Development quota makes caching, coalescing, foreground priority, and resumable background
  work release gates rather than optional optimizations.
- The organization-wide developer budget can couple this app to sibling Client IDs. Sanitized
  budget-pressure telemetry and ownership documentation are required, but no numeric capacity can
  be promised from public documentation alone.
- Batch track and artist client code becomes retirement debt rather than a supported capability;
  its absence from production call paths makes that the YAGNI-aligned target.
- Audio Features, episode/embed handling, playlist scopes, and public MCP/API compatibility are not
  decided indirectly by an app-mode choice; playlist scopes are subsequently resolved by ADR 0006,
  playlist media by ADR 0007, staged embed retirement by ADR 0008, and the Soundcharts-default
  Audio Features policy by ADR 0009.

## Validation

The implementation and rollout plans must include:

- a supported-endpoint and required-field matrix tested against representative restricted
  Development payloads with deprecated and removed fields absent;
- negative tests proving unsupported batch and Extended-only paths cannot become required through
  configuration, fallback, or accidental caller introduction;
- exact tests proving `QUOTA_EXCEEDED` receives one attempt and never enters ordinary 429 retry or
  reset-time logic, while rolling-window 429 behavior remains compatible;
- background deferral and checkpoint-resumption tests that prove quota exhaustion does not lose or
  duplicate collection progress;
- scheduler tests proving foreground work is admitted ahead of background refresh, with bounded
  fairness and no starvation;
- request-coalescing and cache tests covering concurrent one-to-five-user activity and shared
  developer-budget pressure;
- sanitized observability proving metrics and logs contain no tokens, Spotify identifiers,
  listening data, or other PII and do not claim an unpublished quota; and
- public-contract regression tests proving MCP/API errors, Search behavior, and response shapes do
  not change before their dedicated accepted decision.

## Rollback / revisit trigger

Before implementation, amend or supersede this ADR if fresh official evidence shows the restricted
Development surface cannot support a required launch feature. After implementation, roll back to
the common-denominator path by disabling optional work and preserving checkpoints; do not silently
re-enable postponed or Extended-only calls as a recovery mechanism.

Revisit the decision when the active audience must exceed five users, the product qualifies for
Extended Mode, Spotify changes mode eligibility or developer-wide quota semantics, a required
common-denominator endpoint is removed, or measured request pressure remains unacceptable after
caching, coalescing, prioritization, and background deferral.

## Related decisions

- [ADR 0002](0002-azure-target-architecture-and-migration-boundaries.md) selects the small-cohort
  Azure product shape and keeps deployment and public compatibility plan-first.
- [ADR 0003](0003-adopt-staged-account-id-migration.md) governs Spotify account linking and the
  bounded active-cohort reauthorization path.
- [ADR 0004](0004-separate-provider-identities-and-minimize-profile-retention.md) governs provider
  identity separation, profile retention, and OAuth-scope contraction.
- [ADR 0006](0006-bundle-both-playlist-modification-scopes-for-write-access.md) subsequently bundles
  both playlist-modification scopes for every write-enabled initial user.
- [ADR 0007](0007-keep-playlist-media-contract-track-only.md) keeps playlist media track-only.
- [ADR 0008](0008-stage-retirement-of-undocumented-playlist-embed-scraping.md) makes the unofficial
  embed parser transitional compatibility debt with an explicit retirement gate.
- [ADR 0009](0009-use-soundcharts-as-the-default-audio-features-provider.md) subsequently selects
  Soundcharts as the sole default Audio Features provider without relying on Spotify entitlement.
- The dedicated public MCP/API compatibility decision owns Search limits/defaults, outward quota
  errors, and public warning text.
