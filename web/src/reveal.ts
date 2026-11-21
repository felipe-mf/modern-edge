// On narrow screens the detail panel sits below long lists; bring it into view after a pick.
// 1180px is the single-column breakpoint of the split layouts in styles.css; keep the two in step.
export function revealOnNarrow(selector: string) {
  if (!window.matchMedia("(max-width: 1180px)").matches) return;
  requestAnimationFrame(() => document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block: "start" }));
}
