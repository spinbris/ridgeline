# Dashboard release procedure

How a dashboard change or a new period reaches a client's instance. Outlives any single change;
referenced from `dashboard/next.config.ts`. Adapted from an earlier release procedure, rewritten
around this repository's own publish command and re-measured against this tree rather than copied.

**The rule in one line: build, confirm the build succeeded, guard, deploy to preview, smoke check,
and production only ever receives something a preview has proven.**

**And one rule before it: a build ships every project named for publication, not only the one
you are publishing** (step 0). Nothing unnamed ships: the copy, the publish command and the deploy
guard all refuse it. Name the wrong project and one client's periods are served inside another's
instance.

**What this document does not hold.** No live URL, Vercel project, team or password. A client's
deployed instance is engagement material and its details live with that engagement,
under its own controls. Everything below is written with placeholders: `<team>` is the Vercel
team (`--scope`, or env `VERCEL_SCOPE`), `<preview-url>` and `<production-url>` are the instance's.
No Vercel project is linked in this repository's commits; an instance links its own,
locally. **The one exception is the public showcase**, Tropic Ridge (`synthetic_wind`). Its Vercel
project is linked from this `dashboard/`, in the gitignored `dashboard\.vercel\` of the checkout
that deploys it. Its URL is still not recorded in this document.

**Tooling.** The earlier procedure's three check scripts are ported here: the build-output guard
runs inside `publish_period.py --deploy` (step 3), and the
route smoke check and the served-versus-promoted drift check are `scripts/release/` (steps 5 and
8). Both of those are run by the operator against a live site; the repository tests them offline.

---

## Why this exists

In an earlier deployment of this dashboard, every extensionless route on production returned 404 from
the first prebuilt deploy until it was fixed on 17/08/2026, and nobody noticed. Two reasons, and the
procedure closes both:

1. **The app hides it.** Next's `<Link>` and `router.push` navigate client-side, so clicking
   through from `/` works perfectly. Only a *hard load* - typing the URL, refreshing, a bookmark,
   an external link, a screenshot in a deck - reaches the server. Any check that clicks rather
   than hard-loads will pass on a broken site.
2. **The witness checked only JSON.** The period JSONs are real files at literal paths, so they
   resolve whatever the routing config does. They passed green while eight HTML routes were dead.

---

## The procedure

### 0. Precondition - only the projects named for publication ship

**Nothing is published unless it is named** A project ships only
when its binding sets `publish=True` **and** `confidential=False`; a binding that says nothing is
treated as confidential. `dashboard\publish.json` is that list, written from the bindings by
`python scripts/release/write_publish_list.py` and held equal to them by a test. Three places
enforce it:

- `dashboard\scripts\copy-data.js` (every `npm run build`) copies only the named projects, names
  each directory in `data\` it left out (`NOT PUBLISHED: ...`), empties and rewrites
  `public\data\` so nothing unnamed stays fetchable, and fails the build if nothing named has a
  period;
- `publish_period.py` refuses to file a period for a project that is not named or is confidential
  (`PUBLISH REFUSED`), before anything is written;
- the build-output guard (step 3) refuses to deploy a build whose data carries anything unnamed.

Before step 1, confirm the list is current and names what this instance may serve:
`python scripts/release/write_publish_list.py --check`. To publish another project, set the two
attributes on its binding, rerun the script, and commit both.

Also before step 1: `vercel build` needs the instance's Vercel project linked in `dashboard\`,
and its project settings present. On a machine used for more than one instance, confirm which
project is linked before every build. **Measured** (CLI 59.1.3, 30/09/2026):

- **Link interactively:** `vercel link` in `dashboard\`, choosing the instance's project. When it
  offers to connect a Git repository, answer **No**: a connected repository rebuilds on every
  push. Do not link with `--yes`. An agent-driven CLI runs non-interactively, so `--yes` may accept
  the offer instead of declining it.
- **`vercel link` also edits a tracked file.** It appends `.vercel` and `.env*` to
  `dashboard\.gitignore`, with CRLF endings. `.vercel` is already ignored there, so the lines add
  nothing, and committing them reds the line-ending check. Remove exactly the appended lines, never
  with `git checkout`, and confirm `git status` is clean.
- **A link does not bring the project's settings.** An unsettled `vercel build` stops with
  `project_settings_required`. Check the project's variables first with `vercel env ls`, which lists
  names only. Then fetch the settings once with `vercel pull --environment=preview` in `dashboard\`.
  It writes only inside `dashboard\.vercel\`, including a `.env.preview.local` that may hold a
  short-lived Vercel token: never open, copy or commit it. **Do not answer `vercel build --yes`**:
  it pulls without that check.

### 1. Build - through the publish command

```powershell
.\PUBLISH_PERIOD.bat <path-to-period_YYYYMMDD.json> --project <project key>
```

`src/am/publish_period.py` validates the period against the contract this build understands, files
it under `data\<project key>\`, and runs `npm run build`. It refuses rather than defaults, and
refuses to overwrite a period end without `--replace`. Without `--deploy` it stops here, prints
**"Built, NOT deployed"**, and prints the exact sequence `--deploy` would run - the clear, `vercel
build`, the guard, `vercel deploy --prebuilt` - each with the directory it runs from (step 3).

**Only ever prebuilt deploys.** A plain `vercel deploy` makes Vercel's build box run `prebuild` ->
`scripts/copy-data.js`, which reads `../data/`. That directory is gitignored and never uploaded,
so the remote build fails (`Source directory not found`). Building here, where `data/` exists,
and uploading the result with `--prebuilt` is the only path that works. `deploy_steps()` in the
publish module is the one list of the four steps - the clear, `vercel build`, the guard, `vercel
deploy --prebuilt`; what is printed and what is executed cannot differ.

Preview and production are **separate build targets**: `vercel build` and `vercel build --prod`
produce outputs that cannot be deployed to the other. Rebuild when switching.

### 2. Confirm the build actually succeeded - before the guard

**Do not run the guard until the build has reported success.** The guard reads a generated
artefact (`.vercel/output/config.json`). In an earlier deployment, run after a failed build, it
read the previous run's file and passed (17/08/2026: a `vercel build` failed with
`EBUSY` on `out/` - a stale local file lock - and the guard, run separately straight afterwards,
printed PASS on a build that had not happened). **Here it cannot:** the clear before `vercel
build` (step 3) removes the previous output and stamps the build, and the guard refuses output
that is missing, unstamped or older than the stamp.

**A gate that can pass without its input having been produced is not a gate.** Ordering is what
makes it meaningful. `publish_period.py` stops on a non-zero exit from either `vercel` command, so
a failed build never reaches the deploy, and **the guard between them (step 3) also refuses when
`vercel build` reported success but left no build output** - so it cannot pass on a previous run's
file.

Related trap: a local static server started to look at the build (`python -m http.server ... -d
dashboard\out`, or any preview server you pointed at that folder) holds `out/` open and makes the next build fail.
Stop it first, by PID, after confirming by command line that it is yours.

### 3. Guard - before every deploy *(automatic in `--deploy`: `guard_build_output`)*

The property: **`.vercel/output/config.json` contains no Windows path separators.** With
`cleanUrls`, `vercel build` on Windows writes nested routes into the `overrides` map with
backslashes (`"analyst\\drivers"`). The files upload with forward slashes, so on Vercel's Linux
runtime those keys match nothing, the clean-URL mapping never applies, and the route 404s - while
the unconditional `.html -> extensionless` redirect still fires, so the page is unreachable by
any URL. Confirmed in CLI 54.5.1 and 59.1.3.

Under this tree's `trailingSlash: true` the overrides map is empty and the property holds
trivially. **Measured on this tree's first real `vercel build`** (CLI 59.1.3,
preview target):
- `config.json` carries `version: 3`, `routes`, `crons: []`, `framework` (`nextjs`) and no
  `overrides`;
- its two routes are an error handler and a 404 catch-all, whose only path-bearing field is
  `dest: /404.html`;
- the guard passed it, the clear's stamp survived the build, and a project directory planted in the
  built `static\data\` was refused by name. The guard is the tripwire for anyone reintroducing `cleanUrls` or changing the routing
strategy.

**Scripted.** `publish_period.py --deploy` runs four steps,
and prints the same four without it:

1. **clear** - removes `dashboard\.vercel\output` and stamps the start of this build (the project
   link in `.vercel` stays);
2. **`vercel build`**;
3. **the guard** (`guard_build_output`);
4. **`vercel deploy --prebuilt`**.

The guard checks **every string in `config.json` - every key and value, at any depth - except the
value of `routes[].src`**, whose backslashes are regex escapes. So a backslash in an `overrides`
key or `path`, a route's `dest` or `headers.Location`, a cron's `path`, or a field Vercel adds
later is refused. **It fails closed on a shape it does not know:** a `config.json` that is
unreadable, is not a Build Output API `version: 3` document, or has `routes`, `overrides`, a route,
an override, a `dest` or a `path` of an unexpected type is refused, never skipped. It also refuses
output **this build did not produce** - missing (step 2), not preceded by the clear, or older than
it; each pass uses up the clear's stamp - and a `static\data\` that lists or carries anything but
the projects named for publication (step 0). Any refusal ends "Nothing was deployed", and
`vercel deploy` does not run.

**By hand** - the production sequence in step 7 always is - run all four, in order. The clear and
the guard run **from the repository root**, the two `vercel` commands **from `dashboard\`**:

```powershell
.venv\Scripts\python.exe scripts/release/build_guard.py clear   # repository root
vercel build                                                     # in dashboard\ (--prod for production)
.venv\Scripts\python.exe scripts/release/build_guard.py check   # repository root; exit 1 = refused
vercel deploy --prebuilt --yes                                   # in dashboard\ (--prod for production)
```

### 4. Deploy to preview - never straight to production

```powershell
.\PUBLISH_PERIOD.bat <path-to-period_YYYYMMDD.json> --project <project key> --deploy
```

This runs the four steps of step 3 - clear, `vercel build`, the guard, `vercel deploy
--prebuilt` - to a preview. The
earlier rule, "do not use `--deploy` until the guard is scripted", is lifted: the guard is now
inside it, so the command can no longer upload a build nothing has checked.

A preview only. Production is never the publish command's; it prints the production sequence
(the same four steps, with `--prod`) for step 7. The deploy is the publisher's call.

### 5. Smoke check the preview *(script: `scripts/release/route_smoke_check.py`)*

What the script proves (check numbers as it prints them):

- **0** - the pathname-dependent sites in the source are exactly the registered set (the sweep
  below);
- **1** - every route in `dashboard\out\` returns **200 on a hard load, as `text/html`**;
- **2** - an unknown path really **404s**;
- **3** - the served period JSONs **byte-match** `data\<project key>\`;
- **4** - **the served `/data/projects.json` lists exactly the projects named for publication**
  (step 0).

**What it does not prove: the rendered elements.** Every defect in the class below returned a
clean 200 while a pathname-dependent element (header page title, guidance strip, active nav tab)
rendered blank - and this app renders that whole shell on the client, inside `Suspense`, so the
served HTML carries none of it and a script that runs no JavaScript cannot see it (measured:
`dashboard\out\risks\index.html` has no `<header>`, no `aria-current`, no title text). **Those elements are
checked by hand, on every route, in step 6.** This procedure has no automated rendered-page check.

**Preview deployments sit behind Vercel SSO.** Without a protection-bypass secret every request
redirects to Vercel's SSO and an automated check reports failures that are authentication, not
routing. The secret is generated once per instance under **Project Settings -> Deployment
Protection -> Protection Bypass for Automation**, and is never committed.

Measured on the first preview deploy of this tree: a preview answers **302** (a redirect to Vercel's login) without the
bypass.

**The command** (the operator's, against the preview, in the operator's own shell). The secret is
entered without being echoed or kept in the shell's history, and never on a command line:

```powershell
$s = Read-Host -AsSecureString "Vercel automation bypass secret"
$env:VERCEL_AUTOMATION_BYPASS_SECRET = [System.Net.NetworkCredential]::new('', $s).Password
Remove-Variable s
.venv\Scripts\python.exe scripts/release/route_smoke_check.py <preview-url>
Remove-Item Env:VERCEL_AUTOMATION_BYPASS_SECRET     # after step 8's check, if it runs next
```

It needs the build's `dashboard\out\` to enumerate routes from. Exit 0 passes; 1 lists every
failure; 2 is a setup error. It also re-runs the pathname sweep below and fails on an unregistered
site. The secret is read from the environment and never printed or committed.

### 6. Manual check on the preview

Hard-load (do not click through) every route, with `?project=<project key>`:
`/`, `/risks/`, `/mitigations/`, `/changes/`, `/analyst/`, `/analyst/drivers/`,
`/analyst/activities/`, `/analyst/audit/`. On each:

- the role (PM or analyst) is right from the URL alone
- the right nav tab is highlighted
- the header shows the page-title suffix
- the guidance strip is present
- the period freshness banner behaves for the role
- the role toggle works **both** directions
- the footer carries the brand line: "Ridgeline: cost and schedule risk for capital projects, from
  bid to handover. A CBL Analytics product."

And on `/`: the integrated cost-plus-schedule card, whenever the period carries `integrated`.

### 7. Promote to production, then re-check

Run the production sequence `PUBLISH_PERIOD.bat` printed, in order, each from the directory it
names: the clear (repository root), `vercel build --prod` (`dashboard\`; confirm it succeeded), the
guard (repository root), then `vercel deploy --prebuilt --prod` (`dashboard\`). Step 3 has them. Then repeat steps 5
and 6 against `<production-url>`.

`vercel build --prod` rebuilds from whatever `data\` and the working tree hold at that moment, and
nothing checks that this is what the preview proved. So **change nothing in `data\` or the tree
between the preview build and the production build**; if anything changed, go back to step 1.

The post-production check is not optional. It is the record that what was proven on preview is
what production serves.

### 8. Verify - and keep verifying between deploys *(script: `scripts/release/served_vs_promoted_check.py`)*

The property: **per period, the served `schema_version`, `meta.engine_run_date`, `meta.engine_sha`
and `meta.input_sha256` match `data\<project key>\period_*.json`**, checked on a schedule and not
only on a deploy.

Why, from an earlier deployment (21/08/2026): a promotion build was written into `data/`
and sat undeployed for two days while production served the previous set. Step 7 would have caught
it on its first run. Nothing ran it, because **every check in this procedure fires on a deploy**,
and a build promoted and never deployed is invisible to a check triggered by the act that never
happened.

**A procedure whose every gate is triggered by an action cannot see an action that was never
taken.** That is the general form; check the next gate against it.

**The command**, on a schedule and after every deploy:

```powershell
.venv\Scripts\python.exe scripts/release/served_vs_promoted_check.py <site-url>
```

It needs no build: for each project named for publication it compares the four fields of every
`data\<project key>\period_*.json` against the served copy. Exit 0 matches; 1 is drift; 2 means it
could not compare (a fetch failed, or SSO or password protection intercepted), which is neither a
green nor a red. Behind protection, set `VERCEL_AUTOMATION_BYPASS_SECRET` as in step 5; production
behind the instance's password needs a fetch made from a session that has passed it.

---

## The exact-key pathname lookup class - read this before adding a component

**This one pattern produced three separate defects** in an earlier version of this dashboard, and every instance
returned HTTP 200 while rendering a blank element. Status codes cannot see it.

| # | Site | Symptom | Caught by |
|---|---|---|---|
| 1 | `PageNav` active tab (`pathname === href`) | no tab highlighted on any page but `/` | predicted before the change |
| 2 | `AppHeader` `PAGE_TITLES[pathname]` | header page-title suffix blank on 7 of 8 pages | inspecting the preview's rendered HTML |
| 3 | `GuidanceStrip` `GUIDANCE[pathname]` | guidance strip absent on 7 of 8 pages | **shipped to production**, found in post-deploy browser checks |

Defect 3 reached production inside the very deploy that fixed the routing, because verification
checked role, tab and title but not the strip. Fixing one instance of a class without sweeping for
the rest is how the third one shipped.

**Pathname-dependent sites in this tree, swept 23/09/2026 (`usePathname` across `dashboard/`):
five.** The earlier procedure listed four; the fifth was added since.

| Site | Handling |
|---|---|
| `components/AppHeader.tsx` `PAGE_TITLES` | `normalisePath()` |
| `components/GuidanceStrip.tsx` `GUIDANCE` | `normalisePath()` |
| `components/PageNav.tsx` active tab | `normalisePath()` both sides |
| `lib/PeriodContext.tsx` `roleFromPathname` | prefix match (`startsWith`), slash-safe by construction |
| `components/PeriodFreshnessBanner.tsx` role | `roleFromPathname()`, so slash-safe |

**Adding a sixth?** Route any exact-key lookup through `normalisePath()` from
`lib/PeriodContext.tsx`, add it to the table above, and add its rendered element to step 6. When
the smoke check (step 5) re-runs this sweep. Its `KNOWN_PATHNAME_SITES` registers each site by file
**and by the line itself**, so it fails on a new lookup even inside a registered file, and on a
registered site no longer seen; a site edited in place is re-registered there, deliberately.

## Routing invariants

`next.config.ts` sets **`trailingSlash: true`**, so the export emits `<route>/index.html` and every
route resolves by plain directory-index lookup - no rewrite map, and structurally immune to the
separator defect in step 3.

`usePathname()` **returns the trailing slash**: a hard load of `/analyst/drivers/` reports exactly
`"/analyst/drivers/"`. This was measured on a real preview deployment of an earlier version,
not reasoned about.

Consequence: **any exact-match comparison against a slashless route silently fails**, which is
why the lookups above normalise and `ROLE_ROUTES` in `AppHeader` carries the canonical slash
(`/analyst/`) directly - without it the role toggle takes a redirect hop.

If the routing strategy changes, re-run the sweep and re-measure what `usePathname()` returns on a
deployed preview rather than reasoning about it.

## Data flow

`data\<project key>\period_*.json` -> build-time copy by `dashboard\scripts\copy-data.js` into
`dashboard\public\data\`, with an `index.json` manifest per project (a static export cannot list a
directory) -> bundled into `dashboard\out\` -> Vercel static hosting. There is no live data
refresh: a new period appears only after a rebuild and redeploy. Contract:
`src/am/json_writer.py`, the authority.
