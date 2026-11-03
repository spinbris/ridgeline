/**
 * RISKDRV-01 stage 3 (contract 1.7): the shared drivers, beside the risk tornado.
 *
 * Shared drivers are uncertainty on the estimate itself (productivity, quantities), not events,
 * so they never enter the event-risk headline or the bridge. Each row carries the engine's
 * masked leave-one-out on the owner view: what the driver adds to the P80 total cost and to the
 * P80 finish, every other draw held. Every figure is `integrated.shared_drivers`; nothing is
 * computed here. Renders nothing when the register declares no driver.
 */
import { Card } from "@/components/Card";
import { formatAudMillionsDelta, formatLongDate, formatPercent } from "@/lib/formatters";
import type { OwnerView, SharedDriver } from "@/types/period";

function days(n: number | null): string {
  if (n === null) return "-";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)} wd`;
}

export function SharedDriversCard({
  drivers,
  ownerView,
}: {
  drivers: SharedDriver[] | null | undefined;
  ownerView: OwnerView | null | undefined;
}) {
  if (!drivers || drivers.length === 0) return null;
  const p = drivers[0].p_level ?? 80;
  return (
    <Card title="Shared drivers: uncertainty on the estimate, not events">
      <div data-testid="shared-drivers-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left" style={{ color: "var(--color-muted)" }}>
              <th className="py-1 pr-2">Driver</th>
              <th className="py-1 pr-2">Kind</th>
              <th className="py-1 pr-2">Range</th>
              <th className="py-1 pr-2 text-right">Mean duration change</th>
              <th className="py-1 pr-2 text-right">Adds to P{p} total</th>
              <th className="py-1 text-right">Adds to P{p} finish</th>
            </tr>
          </thead>
          <tbody>
            {drivers.map((d) => (
              <tr
                key={d.driver_id}
                className="border-t"
                style={{ borderColor: "var(--color-card-border)" }}
                data-testid={`shared-driver-${d.driver_id}`}
              >
                <td className="py-1 pr-2">
                  {d.driver_id} {d.name}
                  <span className="block text-xs" style={{ color: "var(--color-muted)" }}>
                    {d.acts_on}
                  </span>
                </td>
                <td className="py-1 pr-2">{d.kind === "P" ? "Productivity" : "Quantity"}</td>
                <td className="py-1 pr-2 tabular">{d.range}</td>
                <td className="py-1 pr-2 text-right tabular">
                  {d.mean_duration_change > 0 ? "+" : ""}
                  {formatPercent(d.mean_duration_change, 1)}
                </td>
                <td className="py-1 pr-2 text-right tabular">
                  {d.adds_to_total_dollars === null
                    ? "-"
                    : formatAudMillionsDelta(d.adds_to_total_dollars)}
                </td>
                <td className="py-1 text-right tabular">{days(d.adds_to_finish_days)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs mt-3" style={{ color: "var(--color-muted)" }}>
          {ownerView
            ? `With these drivers the P80 finish is ${formatLongDate(ownerView.p80_finish)}; the headline finish is event risks only. `
            : ""}
          {ownerView?.driver_method ?? ""}
        </p>
      </div>
    </Card>
  );
}
