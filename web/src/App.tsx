import { useQuery } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { useState } from "react";

import { api } from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { SourceContext, SourceSheet } from "./components/Sources";
import { ErrorNote } from "./components/States";
import { formatDate } from "./format";
import { useRoute, type Screen } from "./route";
import { BuildingView } from "./screens/BuildingView";
import { Kpis } from "./screens/Kpis";
import { Payroll } from "./screens/Payroll";
import { Review } from "./screens/Review";

const SCREENS: { id: Screen; label: string }[] = [
  { id: "buildings", label: "Buildings" },
  { id: "kpis", label: "KPIs and AR aging" },
  { id: "review", label: "Review" },
  { id: "payroll", label: "Payroll" },
];

export function App() {
  const route = useRoute();
  const [sourceRef, setSourceRef] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const run = useQuery({ queryKey: ["run"], queryFn: api.run });
  const review = useQuery({ queryKey: ["review"], queryFn: api.review });
  const waiting = review.data?.absences.filter((a) => a.decision === "held_for_review" && !a.review).length;

  const openSource = (ref: string) => {
    setChatOpen(false);
    setSourceRef(ref);
  };

  return (
    <SourceContext.Provider value={openSource}>
      <div className="app">
        <nav className="topnav glass" aria-label="Main">
          <span className="brand">
            Northgate
            {run.data && (
              <small>
                {formatDate(run.data.period_start)} to {formatDate(run.data.period_end)}
                {run.data.payroll_dry_run && " · payroll dry run"}
              </small>
            )}
          </span>
          {SCREENS.map((s) => (
            <a
              key={s.id}
              className="navlink"
              href={`#/${s.id}`}
              aria-current={route.screen === s.id ? "page" : undefined}
            >
              {s.label}
              {s.id === "review" && waiting ? <span className="count">{waiting}</span> : null}
            </a>
          ))}
          <span className="spacer" />
          <button
            className="btn"
            aria-pressed={chatOpen}
            onClick={() => {
              setSourceRef(null);
              setChatOpen(!chatOpen);
            }}
          >
            <MessageSquare /> Ask the data
          </button>
        </nav>

        {run.isError && <ErrorNote error={run.error} />}
        {run.data && route.screen === "buildings" && <BuildingView run={run.data} params={route.params} />}
        {run.data && route.screen === "kpis" && <Kpis />}
        {run.data && route.screen === "review" && <Review />}
        {run.data && route.screen === "payroll" && <Payroll />}
      </div>

      {sourceRef && <SourceSheet sourceRef={sourceRef} onClose={() => setSourceRef(null)} />}
      {chatOpen && <ChatPanel onClose={() => setChatOpen(false)} />}
    </SourceContext.Provider>
  );
}

