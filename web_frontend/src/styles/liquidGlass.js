/**
 * "Liquid Glass" recipe: a raised, frosted surface with a bright specular
 * highlight along the top edge (the "sheen"), a soft inner shadow along the
 * bottom for depth, and a diffuse drop shadow tinted to the surface's own
 * color. This is the shared visual language for every raised interactive
 * element across the app (buttons, pills, cards) — tint the gradient/shadow
 * colors per element, keep the same layering everywhere else, so new UI
 * reads as part of the same system instead of one-off styling.
 */
export function liquidGlass({ top, bottom, border, highlight, innerShadow, outerShadow, blur = 16 }) {
  return {
    background: `linear-gradient(180deg, ${top} 0%, ${bottom} 100%)`,
    border: `1px solid ${border}`,
    backdropFilter: `blur(${blur}px) saturate(160%)`,
    WebkitBackdropFilter: `blur(${blur}px) saturate(160%)`,
    boxShadow: `inset 0 1.5px 1px ${highlight}, inset 0 -2px 6px ${innerShadow}, ${outerShadow}`,
  };
}

/**
 * Recessed variant: same frosted-glass material, but sunk into the surface
 * (a top-edge inner shadow instead of a highlight, no drop shadow) rather
 * than raised off it like a button — for inputs, dropzones, and anything
 * else content sits "inside" rather than "on top of".
 *
 * Elements that need :focus/:hover/:-webkit-autofill overrides can't use
 * this inline (inline styles beat any CSS class rule regardless of
 * selector) — apply it via a CSS class instead, see .sv-auth-input in
 * index.css for the pattern.
 */
export function liquidGlassRecessed({ top, bottom, border, innerHighlight, innerShadow, blur = 12 }) {
  return {
    background: `linear-gradient(180deg, ${top} 0%, ${bottom} 100%)`,
    border: `1px solid ${border}`,
    backdropFilter: `blur(${blur}px) saturate(150%)`,
    WebkitBackdropFilter: `blur(${blur}px) saturate(150%)`,
    boxShadow: `inset 0 1px 2px ${innerShadow}, inset 0 -1px 0 ${innerHighlight}`,
  };
}
