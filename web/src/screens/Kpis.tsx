// KPI panel per building with drill-down: every figure opens the records it was computed from.
// AR aging by bucket, each bucket opening its open items.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Row } from "../api";
import { RecordsTable } from "../components/RecordsTable";
import { ErrorNote, Skeleton } from "../components/States";
import { formatMoney, formatValue, label } from "../format";
import { revealOnNarrow } from "../reveal";

const GROUPS: { title: string; metrics: string[] }[] = [
  { title: "Headcount", metrics: ["contracted_headcount", "active_headcount", "headcount_variance"] },
  { title: "Call-outs and coverage", metrics: ["scheduled_shifts", "callout_shifts", "callout_rate", "fill_rate", "overtime_hours", "overtime_dollars"] },
  { title: "Money", metrics: ["revenue", "labor_cost", "gross_margin", "gross_margin_pct", "unbilled_coverage_count", "unbilled_coverage_dollars"] },
];

const SHORT: Record<string, string> = {
  contracted_headcount: "Contracted",
  active_headcount: "Active",
  headcount_variance: "Variance",
  scheduled_shifts: "Scheduled",
  callout_shifts: "Call-outs",
  callout_rate: "Call-out rate",
  fill_rate: "Fill rate",
  overtime_hours: "OT hours",
  overtime_dollars: "OT $",
  revenue: "Revenue",
  labor_cost: "Labor cost",
  gross_margin: "Margin",
  gross_margin_pct: "Margin %",
  unbilled_coverage_count: "Unbilled",
  unbilled_coverage_dollars: "Unbilled $",
};

const BUCKETS: Record<string, string> = { current: "Current", "1_30": "1–30 days", "31_60": "31–60", "61_90": "61–90", over_90: "Over 90" };

/** Set a figure in semibold only where its sign means trouble: fewer people than contracted, coverage not billed. */
function toneClass(metric: string, value: unknown): string {
  const n = Number(value);
  if (metric === "headcount_variance" && n < 0) return " text-bad";
  if (metric.startsWith("unbilled_") && n > 0) return " text-warn";
  return "";
}

export function Kpis() {
  const panel = useQuery({ queryKey: ["kpis"], queryFn: api.kpis });
  // One detail panel: either a KPI figure or an AR aging bucket.
  const [pick, setPick] = useState<{ building: string; metric: string } | null>(null);
  const [bucket, setBucket] = useState<string | null>(null);
  const [groupTitle, setGroupTitle] = useState(GROUPS[0].title);
  const group = GROUPS.find((g) => g.title === groupTitle) ?? GROUPS[0];
  const showFigure = (building: string, metric: string) => {
    setBucket(null);
    setPick({ building, metric });
    revealOnNarrow(".kpi-grid .detail");
  };
  // Clicking the open bucket again closes it.
  const showBucket = (b: string) => {
    setPick(null);
    if (bucket === b) return setBucket(null);
    setBucket(b);
    revealOnNarrow(".kpi-grid .detail");
  };

  if (panel.isError) return <ErrorNote error={panel.error} />;
  if (!panel.data) return <div className="glass tile"><Skeleton rows={8} /></div>;
  const { buildings, metrics, ar_aging } = panel.data;
  const total = ar_aging.reduce((sum, b) => sum + Number(b.open_amount), 0);

  return (
    <div className="kpi-grid">
      <section className="glass tile kpi-table" aria-label="KPIs by building">
        <div className="tile-title">
          KPIs by building
          <span className="aside segmented small" role="tablist" aria-label="KPI group">
            {GROUPS.map((g) => (
              <button key={g.title} role="tab" className="btn" aria-selected={g === group} aria-pressed={g === group} onClick={() => setGroupTitle(g.title)}>
                {g.title}
              </button>
            ))}
          </span>
        </div>
        <div className="table-wrap">
          <table className="kpi">
            <thead>
              <tr>
                <th>Building</th>
                {group.metrics.map((m) => (
                  <th key={m} className="num" title={metrics[m]}>
                    {SHORT[m]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {buildings.map((row: Row) => (
                <tr key={String(row.building)}>
                  <td className="strong">{String(row.building)}</td>
                  {group.metrics.map((m) => {
                    const active = pick?.building === row.building && pick?.metric === m;
                    return (
                      <td key={m} className="num">
                        <button
                          className={`cell${active ? " active" : ""}${active ? "" : toneClass(m, row[m])}`}
                          aria-pressed={active}
                          onClick={() => showFigure(String(row.building), m)}
                        >
                          {formatValue(m, row[m])}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="secondary table-caption">Click any figure to see its definition and the records behind it.</p>
      </section>

      <section className="glass tile aging" aria-label="AR aging">
        <div className="tile-title">
          AR aging<span className="aside">open {formatMoney(total)}</span>
        </div>
        <ul className="buckets">
          {ar_aging.map((b) => (
            <li key={b.bucket}>
              <button className="bucket" aria-pressed={bucket === b.bucket} onClick={() => showBucket(b.bucket)}>
                <span>{BUCKETS[b.bucket] ?? b.bucket}</span>
                <span className="meter" aria-hidden="true">
                  <span style={{ width: `${total ? (Math.max(0, Number(b.open_amount)) / total) * 100 : 0}%` }} />
                </span>
                <span className="strong">{formatMoney(b.open_amount)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="glass tile detail" aria-label="Detail">
        {pick && <Detail key={`${pick.building}-${pick.metric}`} {...pick} />}
        {bucket && <BucketItems key={bucket} bucket={bucket} total={ar_aging.find((b) => b.bucket === bucket)?.open_amount} />}
        {!pick && !bucket && (
          <p className="empty">Pick a figure in the table or an AR aging bucket: its definition and every record behind it appear here.</p>
        )}
      </section>
    </div>
  );
}

function Detail({ building, metric }: { building: string; metric: string }) {
  const detail = useQuery({ queryKey: ["kpi", building, metric], queryFn: () => api.kpiDetail(building, metric) });
  if (detail.isError) return <ErrorNote error={detail.error} />;
  if (!detail.data) return <Skeleton rows={6} />;
  const d = detail.data;
  return (
    <div className="swap-in">
      <div className="tile-title">
        {building} · {label(metric)}
        <span className="aside">{formatValue(metric, d.value)}</span>
      </div>
      <p className="secondary definition">{d.definition}</p>
      {d.sections.map((s) => (
        <div key={s.title} className="section">
          <div className="section-title">
            {s.title} <span className="secondary">{s.records.length} records</span>
          </div>
          <RecordsTable rows={s.records} />
        </div>
      ))}
    </div>
  );
}

function BucketItems({ bucket, total }: { bucket: string; total: number | undefined }) {
  const items = useQuery({ queryKey: ["ar", bucket], queryFn: () => api.arBucket(bucket) });
  return (
    <>
      <div className="tile-title">
        AR aging · {BUCKETS[bucket] ?? bucket}
        <span className="aside">{formatMoney(total)} open</span>
      </div>
      {items.isError && <ErrorNote error={items.error} />}
      {!items.data && !items.isError && <Skeleton rows={4} />}
      {items.data && (
        <div className="section swap-in">
          <div className="section-title">
            Open items <span className="secondary">{items.data.length} records</span>
          </div>
          <RecordsTable rows={items.data} />
        </div>
      )}
    </>
  );
}
