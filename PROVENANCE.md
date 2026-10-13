# PROVENANCE

This repository was created by RS-A (REPOSPLIT-01) as a cut of an existing
private engineering repository. It is the product; the material specific to the
engagement that repository served does not come across.

## Source

| | |
|---|---|
| source commit | `b3c6191837ab7726e5d63a1883e1dc17855bb389` |
| short | `b3c6191` |
| nearest tag | `DAYRATE-02` (`git describe` = `DAYRATE-02-2-gb3c6191`) |
| source tree OID | `3a5278978faf5f139a830d20055a883e12300b04` |
| tracked files at source | 1218 |
| cut date | 2026-09-01 |
| interpreter used for the gate | CPython 3.12.4 |

## Counts

| | |
|---|---|
| cut | 683 |
| kept | 535 |
| **cut + kept** | **1218 = tracked at source** |
| scrub: changed | 253 (252 rewritten + 1 renamed) |
| scrub: untouched | 282 |
| **changed + untouched** | **535 = kept** |

Both identities were asserted against live state, not carried from a document.
The derivation script was first run against the previous cut commit and had to
reproduce that run's recorded figures, every per-rule contribution included,
before its output here was used.

## What was removed, and why

Four rules, applied by property rather than by directory listing:

- **Engagement material.** Registers, schedules, run outputs, notebooks, stage
  briefs, handovers, research notes and running records.
- **Documents that are not product documents.** Anything carrying a
  confidentiality or non-distribution clause, self-labelling as working notes or
  a draft for review, or recording a point-in-time state since superseded.
  Directory membership was treated as evidence of class, never as the definition
  of it.
- **Binaries carrying client material in compressed members**, found by walking
  every member of every container rather than by any text search over the file.
- **Confidential values**, including figures that no name-based search can reach.

Identifiers, module names and registry keys carrying the engagement name were
renamed. Absolute user paths and the operator username were removed. One golden
workbook had a build path stripped from its metadata, with its sheet data
asserted byte-identical before and after.

## The gate

`scripts/client_gate.py` runs on every push and pull request and fails the build
on any client term, absolute path, username, or confidential value.

The term list is **not in this repository** and never will be: it is the
material being protected. A digest of it is committed, and the gate refuses any
list whose digest does not match it, so a truncated, stale, empty or unset list
fails the build rather than passing it. Every limb has been proven to fire on
planted input and to leave clean input unmatched; a limb that scans zero files
is a failure, because a limb that scans nothing looks exactly like a clean tree.

An allowlist file lists the files exempt from specific limbs, each with a reason,
and is printed on every run. Every entry holds a detection pattern or a
synthetic value. No entry is used to silence a real finding.

## Known limitation

Test-suite state at this commit has not yet been characterised against the
source repository. Some tests depend on inputs that did not come across and are
expected to skip or fail; that comparison is the next step of the work, and
until it is recorded a green or red suite here should not be read as a
regression signal either way.

## Active-management source (RS-A2, 03/09/2026)

| | |
|---|---|
| source repository | the archived AM repository (name withheld here; frozen) |
| source commit | `6c071ff` |
| source tree OID | `68fa81e3188aa79f000c2f4a40c8baed62e16823` |
| landed as | merge `bb8c116`, tag `RS-A2` |

## Freeze (RS-C, 03/09/2026)

| Archive | Tagged freeze commit (the note) | Final commit (note corrected: protected, not archived) | Final tree OID | Last content commit | Tag |
|---|---|---|---|---|---|
| engine repository | `ec10e83b50a0356718fdd77e6dcc5cf32cdbd5aa` | `d6a8172fe779777be7d8c44bfde8e468e58d4d3d` | `9117deea60367d42092364f0000e2b2529619ead` | `4f62147` | `FROZEN-20260903` |
| AM repository | `d00ae040671e714f3efd7241663596d52e874084` | `d9bc617196946cb7d8ffb212654988725036baf3` | `a3adb6a9c537f0f5b966bab32c7c0fa7c2c96865` | `6c071ff` | `FROZEN-20260903` |

Each archive's final commit is its `FROZEN.md`; each names what moved here, what stayed and
why by class, and every ref it holds. `master` locked on GitHub by branch protection with admins
included (Director, 03/09/2026 - protection rather than archiving); a test push to each was
refused (`GH006`). Both private; nothing deleted (DS-4). Nothing is committed to either again.

## G-B baseline moved (WINDINJ-01 Stage B, 09/09/2026)

The wind bit-identity value is the programme's cross-machine reproduction gate. It moved on
this date, by ruling, and this is the record of the move rather than an explanation offered
afterwards.

**Cause.** Director D-1, 09/09/2026, the WINDINJ-01 brief,
§11. The engine pinned `additive_pert_days` at `src/integrated/stage3_config.py:264` over the
`Default_Injection_Method` every register in the tree declares. The pin's stated reason - that
the rows carry no `Gating_Activity_ID` - held on no register: all three carry one on every
Time=Yes row. Each risk's sampled delay is now written to its single gating activity rather
than broadcast across every prefix-matched activity.

**What moved, measured at seed 42 before the bless and blessed to those values.**

| Artefact | Statistic | Before | After |
|---|---|---|---|
| `tests/golden/manifests/wind_synth/canonical.json` (n=10,000) | p50 / p80 / p90 / mean | $5.071M / $6.877M / $7.946M / $5.308M | $5.258M / $7.067M / $8.147M / $5.487M |
| `tests/golden/manifests/synthetic_road/canonical.json` (n=10,000) | p50 / p80 / p90 / mean | $10.651M / $14.224M / $16.269M / $10.964M | $7.916M / $10.446M / $12.002M / $8.218M |
| `tests/fixtures/qraxl01_0_baseline_10k.json` | wind joint P80 | $6,876,655.78 | $7,067,010.11 |
| `tests/fixtures/qraxl01_0_baseline.json` (n=100,000) | wind joint P80 | (re-captured) | $7,027,979.38 |
| `tests/fixtures/sra02_schedule_baseline_10k.json` | wind schedule days mean | 37.493884 | 42.602775 |

**An input identity moved in the same bless, and it is not a headline.** The bless also changed
which *file* the 100k baseline is pinned to. That is a statement about identity of inputs, not
about anything the engine computed, and it is recorded separately here so the two are not read
as one move.

| Artefact | Leaf | Before | After |
|---|---|---|---|
| `tests/fixtures/qraxl01_0_baseline.json` | `/wind_showcase/inputs/register/sha256` | `1d971f47e0000fb6c3d31cf28a29f2aaf3f89a506ed20a01ffca109d8eb8a4d1` | `ab0232f7118b5b9a769fe8d22918eea34c1eacb200cc71ca563c256913f8141b` |

Both digests verified at close-out rather than carried across from the review. `ab0232f7…` is
`tests/fixtures/synthetic_wind/wind_register.xlsx` as it has stood since `45a4d04` (08/09/2026)
and as it hashes on disk today; `1d971f47…` is the version that stood between `55d8ac2` and
`45a4d04`. No engine behaviour follows from this leaf. It feeds only the fail-closed input
assertion in `tests/test_qraxl01_0_bit_identity.py` (`_require_inputs`), whose whole job is to
red as INPUT CHANGED rather than to compute. The artefact's remaining two moved leaves -
`engine_sha` `bf1983b…` -> `0a539cf…` and `branch` `master` -> `feature/WINDINJ-01-stageB` - are
capture provenance and move on every re-capture.

**Why that artefact's "before" is a re-capture and not a measured value.** The gap above is a
reason rather than an omission, and the reason is measurable. `45a4d04` changed the wind
register's content (`1d971f47…` -> `ab0232f7…`) and re-blessed three of the four guards that pin
that register - `qraxl01_0_baseline_10k.json`, `sra02_schedule_baseline_10k.json` and
`manifests/wind_synth/canonical.json`. The 100k baseline was not among them, so from `45a4d04`
onward it carried `1d971f47…` against a tree holding `ab0232f7…` and
`test_wind_showcase_bit_identity` was already hard-red on INPUT CHANGED - before Stage B began,
and still red at `7142b4d`. It is `@pytest.mark.slow`, so no stage-lane run collected it and
nothing said so. Its stored numbers had last been produced at the `55d8ac2` capture, against the
`1d971f47…` register. A "before" measured from that artefact would therefore have been a value
produced against inputs it no longer matched: a stale pin, not a comparator for this change.
Recording it as `(re-captured)` says that. Measured across the artefact's history, this pin has
drifted and been repaired before - it agreed at `55d8ac2`, went red at `45a4d04`, and agrees
again at this bless - so what is new here is not the repair but that it is named.

Per-project direction is not the same, and the strike counts do not predict it. Wind's
integrated P80 rises 2.8%; the road project's falls 26.5%. §18 of
`BRIEF_F35_integrated_delay_baseline.md` measured why: on wind the network already yields less
than the additive sum, so concentrating each risk onto one activity raises the total, and on
the road project it lowers it.

**What did not move.** The cost arm is bit-identical across the change - `np.array_equal` True
and `float.hex()` equal on all 100,000 elements, mean `0x1.325cecb0c6463p+22` on both sides.
That was pinned as exact equality rather than a tolerance (brief §13.1) precisely so this
statement could be made without a band around it.

**Second-machine confirmation is owed and is RS-C's, not this brief's.** The values above were
taken on one machine. Until a second machine reproduces them, G-B has been re-baselined but not
re-proven.

**Confirmed on a second machine, 11/09/2026:** the Mac (Apple M4, arm64), a fresh clone of master
`4a5cb77` on the as-committed lock. `pytest -m golden` passed against these manifests, so G-B is
re-proven for the goldens. The two exact-sample pins (`test_owner_view_seed42_pinned_100k`,
`test_wind_showcase_bit_identity_10k`) land 1-2 ULP away there on the cost layer only, with every
base value and mean bit-identical; the Director ruled them x86-64-only (ARM64ULP-01).
