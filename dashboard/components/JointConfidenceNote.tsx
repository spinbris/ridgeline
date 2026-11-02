/**
 * The joint confidence level, in one sentence (contract 1.5, INTSCURVE-01 Part C; on the report's
 * basis since 1.6, INTVIEW-01 stage 2: the budget includes the base when one was drawn).
 *
 * Every figure is read from `integrated.jcl`; the app states it and computes nothing. Shown
 * beside the headline, never as one: no Australian guidance requires a JCL.
 */

import { formatAud, formatLongDate, formatPercent } from "@/lib/formatters";
import type { IntegratedJcl } from "@/types/period";

export function JointConfidenceNote({ jcl }: { jcl: IntegratedJcl }) {
  return (
    <p className="text-sm" data-testid="jcl-note">
      Joint confidence level <strong>{formatPercent(jcl.jcl, 0)}</strong>: the share of
      iterations that come in at or under {formatAud(jcl.cost_target_dollars)}{" "}
      {jcl.base_drawn
        ? `(the ${formatAud(jcl.declared_base_dollars)} base plus the P${jcl.p_level} contingency) of base, event-risk and delay cost`
        : `(the P${jcl.p_level} contingency; no base estimate was drawn) of event-risk and delay cost`}{" "}
      AND finish by {formatLongDate(jcl.finish_target_date)}. On their own the budget is met in{" "}
      {formatPercent(jcl.cost_confidence, 0)} of iterations and the finish in{" "}
      {formatPercent(jcl.finish_confidence, 0)}. Cost and schedule are sampled jointly, so a risk
      that fires raises both in the same iteration; that makes the joint figure higher than it
      would be if they were drawn independently. The cost here includes delay cost, because the
      budget has to fund it; the figure counts outcomes that meet both, so nothing is counted twice.
    </p>
  );
}
