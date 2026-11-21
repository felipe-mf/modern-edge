// The screen and its filters live in the URL hash, so every view can be linked and reloaded.
// #/buildings/<building>/<date>/<shift> · #/kpis · #/review · #/payroll

import { useEffect, useState } from "react";

export type Screen = "buildings" | "kpis" | "review" | "payroll";

export interface Route {
  screen: Screen;
  params: string[];
}

function parse(hash: string): Route {
  const [screen, ...params] = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const known: Screen[] = ["buildings", "kpis", "review", "payroll"];
  return { screen: known.includes(screen as Screen) ? (screen as Screen) : "buildings", params };
}

export function go(screen: Screen, ...params: string[]): void {
  window.location.hash = `/${[screen, ...params].map(encodeURIComponent).join("/")}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
