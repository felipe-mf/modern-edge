import { useQuery } from "@tanstack/react-query";
import { Building2, ChartColumn, ClipboardCheck, MessageSquare, Wallet, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { api } from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { SourceContext, SourceSheet } from "./components/Sources";
import { ErrorNote } from "./components/States";
import { useRoute, type Screen } from "./route";
import { BuildingView } from "./screens/BuildingView";
import { Kpis } from "./screens/Kpis";
import { Payroll } from "./screens/Payroll";
import { Review } from "./screens/Review";

// The screens, in two labelled sections: what happened on site and in the money, then what reached payroll.
const SECTIONS: { title: string; screens: { id: Screen; label: string; icon: LucideIcon }[] }[] = [
  {
    title: "Operations",
    screens: [
      { id: "buildings", label: "Buildings", icon: Building2 },
      { id: "kpis", label: "KPIs and AR aging", icon: ChartColumn },
    ],
  },
  {
    title: "Payroll",
    screens: [
      { id: "review", label: "Review", icon: ClipboardCheck },
      { id: "payroll", label: "Payroll", icon: Wallet },
    ],
  },
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
      <div className="shell">
        <aside className="sidebar glass">
          <div className="brand">
            Northgate
            {/* The period is not repeated here; only a dry run, which changes what payroll means, is flagged. */}
            {run.data?.payroll_dry_run && <small>payroll dry run</small>}
          </div>
          <nav className="sidenav" aria-label="Main">
            {SECTIONS.map((section) => (
              <div key={section.title} className="navsection">
                <div className="navtitle">{section.title}</div>
                {section.screens.map((s) => (
                  <a
                    key={s.id}
                    className="navlink"
                    href={`#/${s.id}`}
                    aria-current={route.screen === s.id ? "page" : undefined}
                  >
                    <s.icon aria-hidden="true" />
                    <span className="navlabel">{s.label}</span>
                    {s.id === "review" && waiting ? <span className="count">{waiting}</span> : null}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <div className="navtitle ask-title">Assistant</div>
          <button
            className="btn ask"
            aria-pressed={chatOpen}
            onClick={() => {
              setSourceRef(null);
              setChatOpen(!chatOpen);
            }}
          >
            <MessageSquare /> Ask the data
          </button>
        </aside>

        <main className="app">
        {run.isError && <ErrorNote error={run.error} />}
        {run.data && route.screen === "buildings" && <BuildingView run={run.data} params={route.params} />}
        {run.data && route.screen === "kpis" && <Kpis />}
        {run.data && route.screen === "review" && <Review />}
        {run.data && route.screen === "payroll" && <Payroll />}
        </main>
      </div>

      {sourceRef && <SourceSheet sourceRef={sourceRef} onClose={() => setSourceRef(null)} />}
      {chatOpen && <ChatPanel onClose={() => setChatOpen(false)} />}
    </SourceContext.Provider>
  );
}

