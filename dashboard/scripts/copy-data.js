/**
 * AM03 build-time data copy.
 *
 * Copies ../data/<project>/period_*.json into public/data/<project>/ so the static export can
 * fetch them at runtime - **for the projects named for publication, and no others**.
 *
 * Cross-platform by construction: pure Node fs/path, no shell
 * commands. Works on Windows (production environment) and
 * Linux/macOS identically.
 *
 * Hooked as the `prebuild` npm script. Adding a new period requires
 * a rebuild and redeploy (no ISR, no live refresh in v1).
 *
 * Stage 7 part C (B-2): **one directory per project.** D-7 rules that one install serves many
 * projects, and the flat layout could not deliver it - `period_20260930.json` is one filename,
 * so two projects could not both close a period on 30 September. The engine now writes
 * `data/<project>/period_YYYYMMDD.json` (`src/am/run_period.py`).
 *
 * The PATH is authoritative for which project a period belongs to; `meta.project_key` inside the
 * document is corroborating, because §5.2 ruled the key OPTIONAL so that no existing period JSON
 * was invalidated. This script therefore keys on the directory and never reads the documents.
 *
 * DASHGATE-01 (RELEASE-01 D-5 as amended): **nothing is published unless it is named.** The named
 * projects are `dashboard/publish.json`, written from the project bindings by
 * `scripts/release/write_publish_list.py` and held equal to them by a test. It is loaded with
 * `require` - it is configuration, not a period document. A project directory in `data/` that it
 * does not name is not copied, and is named on stderr. The pre-part-C FLAT `data/period_*.json`
 * layout (`_unkeyed`) is unnamed by definition, so it is no longer copied either. With nothing
 * named, or nothing named that has a period, the build fails rather than shipping an empty picker.
 *
 * `public/data/` is derived: it is emptied and rewritten on every run, so a project once copied
 * and since unnamed or removed leaves nothing fetchable behind (the `other_project/` ghost).
 *
 * Per AM03 v1.1.1 §4 / §5.A.5.
 */

const fs = require("node:fs");
const path = require("node:path");

const DASHBOARD_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(DASHBOARD_ROOT, "..");
const SOURCE_DIR = path.join(REPO_ROOT, "data");
const TARGET_DIR = path.join(DASHBOARD_ROOT, "public", "data");
const PUBLISH_LIST = path.join(DASHBOARD_ROOT, "publish.json");

/** Periods produced before part C, sitting flat in data/. */
const UNKEYED = "_unkeyed";
const PERIOD_RE = /^period_\d{8}\.json$/;

function refuse(message) {
  console.error(`[copy-data] ${message}`);
  process.exit(1);
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/** The projects named for publication (DASHGATE-01 P2). Refuses when there are none. */
function namedProjects() {
  if (!fs.existsSync(PUBLISH_LIST)) {
    refuse(
      `No publish list at ${PUBLISH_LIST}: nothing is named for publication.\n` +
        `[copy-data] Run python scripts/release/write_publish_list.py from the repository root.`,
    );
  }
  const declared = require(PUBLISH_LIST);
  const names = Array.isArray(declared.projects) ? declared.projects : [];
  if (names.length === 0) {
    refuse(
      `${PUBLISH_LIST} names no project for publication. Nothing is published unless it is\n` +
        `[copy-data] named: set publish=True, confidential=False on a binding and regenerate it.`,
    );
  }
  return new Set(names);
}

/** Map of project key -> sorted period filenames, read from the directory layout alone. */
function discoverProjects() {
  const byProject = new Map();

  const flat = fs.readdirSync(SOURCE_DIR).filter((n) => PERIOD_RE.test(n));
  if (flat.length > 0) byProject.set(UNKEYED, flat.sort());

  for (const entry of fs.readdirSync(SOURCE_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const periods = fs
      .readdirSync(path.join(SOURCE_DIR, entry.name))
      .filter((n) => PERIOD_RE.test(n))
      .sort();
    // A directory with no periods is skipped rather than listed empty: a project the picker
    // offers and then cannot load is worse than one it does not offer.
    if (periods.length > 0) byProject.set(entry.name, periods);
  }

  return byProject;
}

function copyPeriodJsons() {
  if (!fs.existsSync(SOURCE_DIR)) {
    refuse(
      `Source directory not found: ${SOURCE_DIR}\n` +
        `[copy-data] The period engine must run before the dashboard is built.`,
    );
  }

  const named = namedProjects();
  const byProject = discoverProjects();

  if (byProject.size === 0) {
    refuse(
      `No period_YYYYMMDD.json files found under ${SOURCE_DIR}.\n` +
        `[copy-data] Expected data/<project>/period_YYYYMMDD.json. Run RUN_PERIOD.bat first.`,
    );
  }

  const shipped = [...byProject.entries()].filter(([project]) => named.has(project)).sort();
  for (const [project] of [...byProject.entries()].sort()) {
    if (named.has(project)) continue;
    const label = project === UNKEYED ? `${project} (pre-part-C flat layout)` : project;
    console.error(`[copy-data] NOT PUBLISHED: ${label} - not named in dashboard/publish.json`);
  }
  if (shipped.length === 0) {
    refuse(
      `None of the projects named for publication (${[...named].join(", ")}) has a period ` +
        `under ${SOURCE_DIR}.\n[copy-data] Refusing to build a dashboard with nothing in it.`,
    );
  }

  // The target is derived: empty it entirely, so nothing a previous run copied - a project since
  // unnamed or removed, a stale manifest - stays fetchable by URL.
  fs.rmSync(TARGET_DIR, { recursive: true, force: true });
  ensureDir(TARGET_DIR);

  const projects = [];
  for (const [project, periods] of shipped) {
    const from = path.join(SOURCE_DIR, project);
    const to = path.join(TARGET_DIR, project);
    ensureDir(to);
    for (const name of periods) {
      fs.copyFileSync(path.join(from, name), path.join(to, name));
    }
    // Per-project manifest: a static export cannot list a directory over HTTP, so the loader
    // has nothing to enumerate without one.
    fs.writeFileSync(
      path.join(to, "index.json"),
      JSON.stringify({ periods, generated_at: new Date().toISOString() }, null, 2),
      "utf-8",
    );
    projects.push({ project, periods: periods.length });
  }

  // Root manifest: which projects exist. The app reads this first to decide what `?project=`
  // may name and what the picker offers.
  fs.writeFileSync(
    path.join(TARGET_DIR, "projects.json"),
    JSON.stringify(
      { projects: projects.map((p) => p.project), generated_at: new Date().toISOString() },
      null,
      2,
    ),
    "utf-8",
  );

  const total = projects.reduce((n, p) => n + p.periods, 0);
  console.log(
    `[copy-data] Copied ${total} period file(s) across ${projects.length} project(s) to ${TARGET_DIR}.`,
  );
  for (const { project, periods } of projects) {
    console.log(`[copy-data]   ${project}: ${periods} period(s)`);
  }
}

copyPeriodJsons();
