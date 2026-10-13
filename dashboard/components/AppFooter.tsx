/**
 * Footer with engine-run metadata and the provenance stamp.
 *
 * Mirrors the mockup's `.app-footer`: small print across the bottom
 * of every page showing the engine run hash, register version,
 * iteration count, and seed. Surfaces the audit lineage to the
 * dashboard reader without occupying primary screen real estate.
 *
 * Stage 7 part A (D-3): the provenance stamp the app has been RECEIVING since AM09 is now
 * displayed. Before this, the footer showed only `meta.engine_run_hash` - a `uuid.uuid4()`
 * minted per run (`src/am/json_writer.py:163`), which identifies an execution and nothing
 * reproducible - while `engine_sha`, `engine_tree_dirty` and `input_sha256` arrived in every
 * period JSON and were rendered nowhere. A published figure should be traceable from the page it
 * is published on.
 *
 * `engine_tree_dirty` is the one that mattered most: it is a WARNING, it is true on real
 * artefacts (the local `data/period_20260228.json` carries `true`), and the reader could not see
 * it. A number produced by uncommitted code cannot be reproduced from the SHA beside it, so it
 * gets a visible marker rather than a subtle one - a warning nobody notices is not a warning.
 * All three stay optional: a pre-AM09 artefact lacks them and must still render.
 */

"use client";

import { usePeriodContext } from "@/lib/PeriodContext";
import { PRODUCT_LINE } from "@/lib/product";
import type { InputDigest } from "@/types/period";

/** Digest methods, spelled for a reader rather than as the contract's enum value. */
const DIGEST_METHOD_LABEL: Record<InputDigest["method"], string> = {
  git_blob_oid: "git blob OID",
  sha256_bytes: "SHA-256 of bytes",
};

function digestTitle(inputs: Record<string, InputDigest>): string {
  return Object.entries(inputs)
    .map(([name, d]) => `${name}: ${d.value} (${DIGEST_METHOD_LABEL[d.method]})`)
    .join("\n");
}

/** RIDGELINE-01 (R-13, Director W6): the product and its maker, on every page, data or not. */
function BrandLine() {
  return <div className="w-full">{PRODUCT_LINE}</div>;
}

export function AppFooter() {
  const { status } = usePeriodContext();
  if (status.kind !== "ready") {
    return (
      <footer
        className="px-6 py-3 mt-8 bg-white border-t text-xs"
        style={{ borderColor: "var(--color-card-border)", color: "var(--color-muted)" }}
      >
        <BrandLine />
      </footer>
    );
  }

  const m = status.data.meta;
  const a = status.data.audit;
  const inputs = m.input_sha256 as Record<string, InputDigest> | undefined;

  return (
    <footer
      className="flex flex-wrap items-center justify-between gap-2 px-6 py-3 mt-8 bg-white border-t text-xs"
      style={{
        borderColor: "var(--color-card-border)",
        color: "var(--color-muted)",
      }}
    >
      <div>
        Engine: {a.config.engine} -{" "}
        {m.iterations.toLocaleString()} iterations - seed {m.seed} -
        register {m.register_version}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span>
          Engine run {m.engine_run_date.slice(0, 10)} -{" "}
          <span className="tabular">{m.engine_run_hash.slice(0, 8)}</span>
        </span>
        {m.engine_sha ? (
          <span title={`Engine commit ${m.engine_sha}`}>
            - engine <span className="tabular">{m.engine_sha.slice(0, 8)}</span>
          </span>
        ) : null}
        {m.engine_tree_dirty ? (
          <span
            className="px-1.5 py-0.5 rounded font-medium"
            style={{ backgroundColor: "#fef3c7", color: "#92400e" }}
            title={
              "The engine's working tree had uncommitted changes when this period was produced, " +
              "so the commit named above is not the code that ran. These figures cannot be " +
              "reproduced from that commit alone."
            }
          >
            uncommitted changes
          </span>
        ) : null}
        {inputs ? (
          <span title={digestTitle(inputs)}>
            - {Object.keys(inputs).length} inputs digested
          </span>
        ) : null}
      </div>
      <BrandLine />
    </footer>
  );
}
