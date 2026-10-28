// Shared "appear in front of you" entrance animation for chart/visualizer
// panels -- keyframes live in index.css (@keyframes sv-panel-reveal) since
// inline styles can't define them; this just staggers each panel's delay
// by its call order on the page.
export function revealStyle(i = 0, delayStep = 0.07) {
  return {
    animationName: "sv-panel-reveal",
    animationDuration: "0.6s",
    animationTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
    animationFillMode: "both",
    animationDelay: `${i * delayStep}s`,
  };
}
