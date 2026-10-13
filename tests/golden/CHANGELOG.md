# Golden number movements

Audit trail of blessed golden-headline movements. PUBLIC projects record numbers here; CONFIDENTIAL projects record a no-number line here and the numbers in the gitignored local/CHANGELOG.local.md.

- 2026-07-24 wind_synth::canonical P80 (none) -> $6.877M - reason: GOLDEN01 initial baseline (Director BUILD GO 24/07/2026) (by Steve)
    p50: (none) -> $5.071M  p80: (none) -> $6.877M  p90: (none) -> $7.946M  mean: (none) -> $5.308M
- 2026-07-24 refproject::canonical headline moved - reason: GOLDEN01 initial baseline (Director BUILD GO 24/07/2026) (blessed by Steve; numbers in local/CHANGELOG.local.md)
- 2026-08-18 wind_synth::canonical P80 $6.877M -> $6.877M - reason: PROVCRLF01 G3: input identity moves from a byte-hash of the working copy to the git blob OID. The previous xer digest recorded this machine's CRLF checkout and was unreproducible on any compliant checkout (Director-approved brief PROVCRLF01, 18/08/2026). (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-08-18 refproject::canonical headline moved - reason: PROVCRLF01 G3: input identity moves to {method, value} records. Digest values only; every headline unchanged (Director-approved brief PROVCRLF01, 18/08/2026). (blessed by Steve; numbers in local/CHANGELOG.local.md)

## 2026-08-18 - PROVCRLF01: input identity moved to git blob OIDs

The headline movement lines above record no movement, which is the point: this
stage changed how an input is IDENTIFIED, not what it contains. G3 requires the
digest values themselves on the record, so they are here. wind_synth is a
public-tier project, so the values are safe to commit.

`wind_synth::canonical` - `inputs_sha256`, bare digest -> `{method, value}`:

| Input | Before (sha256 of working copy) | After (git blob OID) |
|-------|--------------------------------|----------------------|
| `tests/fixtures/synthetic_wind/wind_schedule.xer` | `c246a1967922296e9682d0e3a00a2ca7cfd40ca62ab45ac82e36f3ae99f07b6e` | `5cbed8f12994c6f82b1c4809dd8791f58add2764` |
| `tests/fixtures/synthetic_wind/wind_register.xlsx` | `1c98cc4b188651f2e5ae3f5f5c2108e0c84eeb24cd628b9d16e28ea1e4885d87` | `0885e2419c6916b6a72431cbfa29ed2274e2db9a` |

Both now carry `"method": "git_blob_oid"`.

The xer digest MUST move and the old value must not come back. `c246a196...`
was the sha256 of this machine's CRLF checkout; the repo declares
`* text=auto eol=lf`, so any compliant checkout holds LF and hashes to
`2120db0d...` instead. The gate was green on the XPS and red everywhere else.
`5cbed8f1...` is the blob OID git records for that content, identical at HEAD,
at the AM pin `27ccd3f`, at `5d66655` and at `master` - and unchanged across the
PIN-DRIFT-01 bump, which is the proof the content never moved while the digest
did.

All four headline stats are bit-identical across the re-bless
(`0x1.35892cca92af2p+22` / `0x1.a3b7bf20a2ea9p+22` / `0x1.e4fc8f04ba15cp+22` /
`0x1.43fccc6479af3p+22`).

`refproject::canonical` was re-blessed in the same pass - required, because the
contract change makes every pre-existing manifest unreadable, and the gate is
red until each one moves. Its values stay in the gitignored local tier. All
three of its inputs record `"method": "sha256_bytes"`: they are client files
under gitignored paths, so git tracks none of them and the byte-hash fallback
applies. That is the fallback working as designed, and it is now visible in the
manifest rather than assumed.

**Residual, recorded not fixed:** one of those three fallback inputs is a `.xer`
- untracked TEXT - so its digest remains line-ending-dependent in exactly the
way this stage removed for wind. Nothing in scope here changes that: the file is
not in any repo, so there is no blob OID to use and no `.gitattributes` to
apply. It is now honestly LABELLED `sha256_bytes` rather than silently
byte-hashed, which is the difference between a known limit and a defect. Raised
as a follow-up rather than resolved.
- 2026-09-03 wind_synth::canonical P80 $6.877M -> $6.877M - reason: RS-C P-6: provenance refresh on the 3.12 lock, clean tree; numbers asserted identical (Director 03/09/2026) (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-03 wind_synth::canonical P80 $6.877M -> $6.877M - reason: RS-D parts 2/6 (D-14, D-18): the wind register gains the methodology settings rows (four calibration tolerances, default injection method) and a Mapping Injection_Method column; every headline number identical (dry-run diff unchanged); input hash re-blessed under the Director's authority of 03/09/2026 (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-03 wind_synth::canonical P80 $6.877M -> $6.877M - reason: RS-D parts 2/6: provenance refresh on the clean tree at 96a9017; numbers identical (Director authority 03/09/2026) (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-05 wind_synth::canonical P80 $6.877M -> $6.877M - reason: 3c Part C: wind fixture regenerated so its TOC carries the run section, the contract version and the corrected MC_Params description. Input hash only - every headline bit-identical at n=10000/seed=42, verified before the bless. Director authority 05/09/2026. (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-05 wind_synth::canonical P80 $6.877M -> $6.877M - reason: Provenance refresh on the clean tree: the TOC re-bless was stamped 3c-dirty because the regenerated fixture was still uncommitted. Numbers identical; engine_ref only. Director authority 05/09/2026. (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-07 synthetic_road::canonical P80 (none) -> $14.224M - reason: ROAD-01 B-3: first baseline for synthetic project #2 (Kestrel Highway Upgrade). A NEW project's manifest - no existing number moves, which the golden gate confirms separately. (by Director, ROAD-01 signed 07/09/2026)
    p50: (none) -> $10.651M  p80: (none) -> $14.224M  p90: (none) -> $16.269M  mean: (none) -> $10.964M
- 2026-09-08 wind_synth::canonical P80 $6.877M -> $6.877M - reason: F-30 tie-band row Schedule_Top3_Tie_Tolerance_Pct added to every register by the scaffolder (Director, 08/09/2026); headlines unchanged, input hashes moved (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-08 synthetic_road::canonical P80 $14.224M -> $14.224M - reason: F-30 tie-band row Schedule_Top3_Tie_Tolerance_Pct added to every register by the scaffolder (Director, 08/09/2026); headlines unchanged, input hashes moved (by Steve)
    p50: $10.651M -> $10.651M  p80: $14.224M -> $14.224M  p90: $16.269M -> $16.269M  mean: $10.964M -> $10.964M
- 2026-09-08 wind_synth::canonical P80 $6.877M -> $6.877M - reason: provenance refresh on the clean tree after the F-30 commit (45a4d04): same inputs, same headlines; the engine_ref stamped at the bless carried -dirty (by Steve)
    p50: $5.071M -> $5.071M  p80: $6.877M -> $6.877M  p90: $7.946M -> $7.946M  mean: $5.308M -> $5.308M
- 2026-09-08 synthetic_road::canonical P80 $14.224M -> $14.224M - reason: provenance refresh on the clean tree after the F-30 commit (45a4d04): same inputs, same headlines; the engine_ref stamped at the bless carried -dirty (by Steve)
    p50: $10.651M -> $10.651M  p80: $14.224M -> $14.224M  p90: $16.269M -> $16.269M  mean: $10.964M -> $10.964M
- 2026-09-09 wind_synth::canonical P80 $6.877M -> $7.067M - reason: WINDINJ-01 Stage B, Director D-1 09/09/2026: the engine no longer pins additive_pert_days over the register's declared Default_Injection_Method. Every register in the tree declares discrete_event_additive_days and carries a Gating_Activity_ID on every Time=Yes row, so each risk's sampled delay is now written to its single gating activity instead of broadcast across every prefix-matched activity. Cost arm bit-identical (float.hex, all 100,000 elements); the schedule arm moves and these headlines with it. (by Steve)
    p50: $5.071M -> $5.258M  p80: $6.877M -> $7.067M  p90: $7.946M -> $8.147M  mean: $5.308M -> $5.487M
- 2026-09-09 synthetic_road::canonical P80 $14.224M -> $10.446M - reason: WINDINJ-01 Stage B, Director D-1 09/09/2026: the engine no longer pins additive_pert_days over the register's declared Default_Injection_Method. Every register in the tree declares discrete_event_additive_days and carries a Gating_Activity_ID on every Time=Yes row, so each risk's sampled delay is now written to its single gating activity instead of broadcast across every prefix-matched activity. Cost arm bit-identical (float.hex, all 100,000 elements); the schedule arm moves and these headlines with it. (by Steve)
    p50: $10.651M -> $7.916M  p80: $14.224M -> $10.446M  p90: $16.269M -> $12.002M  mean: $10.964M -> $8.218M
- 2026-09-09 wind_synth::canonical P80 $7.067M -> $7.067M - reason: WINDINJ-01 Stage B, Director D-1 09/09/2026: the engine no longer pins additive_pert_days over the register's declared Default_Injection_Method. Every register in the tree declares discrete_event_additive_days and carries a Gating_Activity_ID on every Time=Yes row, so each risk's sampled delay is now written to its single gating activity instead of broadcast across every prefix-matched activity. Cost arm bit-identical (float.hex, all 100,000 elements); the schedule arm moves and these headlines with it. (by Steve)
    p50: $5.258M -> $5.258M  p80: $7.067M -> $7.067M  p90: $8.147M -> $8.147M  mean: $5.487M -> $5.487M
- 2026-09-09 synthetic_road::canonical P80 $10.446M -> $10.446M - reason: WINDINJ-01 Stage B, Director D-1 09/09/2026: the engine no longer pins additive_pert_days over the register's declared Default_Injection_Method. Every register in the tree declares discrete_event_additive_days and carries a Gating_Activity_ID on every Time=Yes row, so each risk's sampled delay is now written to its single gating activity instead of broadcast across every prefix-matched activity. Cost arm bit-identical (float.hex, all 100,000 elements); the schedule arm moves and these headlines with it. (by Steve)
    p50: $7.916M -> $7.916M  p80: $10.446M -> $10.446M  p90: $12.002M -> $12.002M  mean: $8.218M -> $8.218M
- 2026-09-17 wind_synth::canonical P80 $7.067M -> $7.484M - reason: METHFIRE-01, SPEC R-10, Director sign-off on the old-versus-new table 17/09/2026: a risk has one probability and one fire draw. The Stage 3 replay now fires each risk on the cost arm's draw against Probability, correlated within its correlation group, instead of its own independent Bernoulli on Probability (Time); severity was already shared. Cost arm bit-identical (float.hex, all 10,000 elements, both projects, seed 42); schedule means move under 0.2%, the schedule tail widens and these headlines with it. (by Steve)
    p50: $5.258M -> $5.255M  p80: $7.067M -> $7.484M  p90: $8.147M -> $8.737M  mean: $5.487M -> $5.485M
- 2026-09-17 synthetic_road::canonical P80 $10.446M -> $11.311M - reason: METHFIRE-01, SPEC R-10, Director sign-off on the old-versus-new table 17/09/2026: a risk has one probability and one fire draw. The Stage 3 replay now fires each risk on the cost arm's draw against Probability, correlated within its correlation group, instead of its own independent Bernoulli on Probability (Time); severity was already shared. Cost arm bit-identical (float.hex, all 10,000 elements, both projects, seed 42); schedule means move under 0.2%, the schedule tail widens and these headlines with it. (by Steve)
    p50: $7.916M -> $7.816M  p80: $10.446M -> $11.311M  p90: $12.002M -> $13.321M  mean: $8.218M -> $8.218M
- 2026-09-17 wind_synth::canonical P80 $7.484M -> $7.484M - reason: provenance refresh on the clean tree after the METHFIRE-01 commits (73b9859): same inputs, same headlines; the engine_ref stamped at the 17/09 bless carried -dirty (by Steve)
    p50: $5.255M -> $5.255M  p80: $7.484M -> $7.484M  p90: $8.737M -> $8.737M  mean: $5.485M -> $5.485M
- 2026-09-17 synthetic_road::canonical P80 $11.311M -> $11.311M - reason: provenance refresh on the clean tree after the METHFIRE-01 commits (73b9859): same inputs, same headlines; the engine_ref stamped at the 17/09 bless carried -dirty (by Steve)
    p50: $7.816M -> $7.816M  p80: $11.311M -> $11.311M  p90: $13.321M -> $13.321M  mean: $8.218M -> $8.218M
- 2026-09-17 wind_synth::canonical P80 $7.484M -> $7.521M - reason: RNGSTREAM-01, Director sign-off on the old-versus-new table with bootstrap standard errors 17/09/2026: the severity uniforms move to a stream of their own (src.rng_streams), independent of the fire draw, which was seeded with the same integer. Fire records bit-identical on both projects; every statistic within 1.26 SE of a difference, the change is resampling noise on registers the old coupling did not reach. (by Steve)
    p50: $5.255M -> $5.271M  p80: $7.484M -> $7.521M  p90: $8.737M -> $8.705M  mean: $5.485M -> $5.485M
- 2026-09-17 synthetic_road::canonical P80 $11.311M -> $11.369M - reason: RNGSTREAM-01, Director sign-off on the old-versus-new table with bootstrap standard errors 17/09/2026: the severity uniforms move to a stream of their own (src.rng_streams), independent of the fire draw, which was seeded with the same integer. Fire records bit-identical on both projects; every statistic within 1.26 SE of a difference, the change is resampling noise on registers the old coupling did not reach. (by Steve)
    p50: $7.816M -> $7.877M  p80: $11.311M -> $11.369M  p90: $13.321M -> $13.366M  mean: $8.218M -> $8.263M
- 2026-09-17 wind_synth::canonical P80 $7.521M -> $7.521M - reason: provenance refresh on the clean tree after the RNGSTREAM-01 commits (70ecc5b): same inputs, same headlines; the engine_ref stamped at the 17/09 bless carried -dirty (by Steve)
    p50: $5.271M -> $5.271M  p80: $7.521M -> $7.521M  p90: $8.705M -> $8.705M  mean: $5.485M -> $5.485M
- 2026-09-17 synthetic_road::canonical P80 $11.369M -> $11.369M - reason: provenance refresh on the clean tree after the RNGSTREAM-01 commits (70ecc5b): same inputs, same headlines; the engine_ref stamped at the 17/09 bless carried -dirty (by Steve)
    p50: $7.877M -> $7.877M  p80: $11.369M -> $11.369M  p90: $13.366M -> $13.366M  mean: $8.263M -> $8.263M
- 2026-10-02 wind_synth::canonical P80 $7.521M -> $7.521M - reason: PUBLICFACE-01, Director approval of the field-level diff 02/10/2026: the fixture registers and the template name the product's maker as creator (docProps and Set_PreparedBy), so the register input digests move; same headlines, no number moved. engine_ref is the clean commit ab872f3's describe. (by Steve)
    p50: $5.271M -> $5.271M  p80: $7.521M -> $7.521M  p90: $8.705M -> $8.705M  mean: $5.485M -> $5.485M
- 2026-10-02 synthetic_road::canonical P80 $11.369M -> $11.369M - reason: PUBLICFACE-01, Director approval of the field-level diff 02/10/2026: the fixture registers and the template name the product's maker as creator (docProps and Set_PreparedBy), so the register input digests move; same headlines, no number moved. engine_ref is the clean commit ab872f3's describe. (by Steve)
    p50: $7.877M -> $7.877M  p80: $11.369M -> $11.369M  p90: $13.366M -> $13.366M  mean: $8.263M -> $8.263M
- 2026-10-08 wind_synth::canonical P80 $7.521M -> $7.521M - reason: CONFIGTRUTH-01 P5: MC_Params seed row relabelled; input digest only (Director 08/10/2026: 'bless yes') (by Steve)
    p50: $5.271M -> $5.271M  p80: $7.521M -> $7.521M  p90: $8.705M -> $8.705M  mean: $5.485M -> $5.485M
- 2026-10-08 synthetic_road::canonical P80 $11.369M -> $11.369M - reason: CONFIGTRUTH-01 P5: MC_Params seed row relabelled; input digest only (Director 08/10/2026: 'bless yes') (by Steve)
    p50: $7.877M -> $7.877M  p80: $11.369M -> $11.369M  p90: $13.366M -> $13.366M  mean: $8.263M -> $8.263M
- 2026-10-08 wind_synth::canonical P80 $7.521M -> $7.521M - reason: CONFIGTRUTH-01: golden provenance refresh on the clean tree at 928f8ae (the P5 bless, Director 08/10/2026: 'bless yes'); engine_ref only (by Steve)
    p50: $5.271M -> $5.271M  p80: $7.521M -> $7.521M  p90: $8.705M -> $8.705M  mean: $5.485M -> $5.485M
- 2026-10-08 synthetic_road::canonical P80 $11.369M -> $11.369M - reason: CONFIGTRUTH-01: golden provenance refresh on the clean tree at 928f8ae (the P5 bless, Director 08/10/2026: 'bless yes'); engine_ref only (by Steve)
    p50: $7.877M -> $7.877M  p80: $11.369M -> $11.369M  p90: $13.366M -> $13.366M  mean: $8.263M -> $8.263M
