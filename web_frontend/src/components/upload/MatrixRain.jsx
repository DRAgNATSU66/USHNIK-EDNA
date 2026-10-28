import { useEffect, useRef } from "react";

const GLYPHS = "ACGT01ACGT広コソヲ10".split("");
const FONT_SIZE = 12;

export default function MatrixRain() {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");

    let cols, drops, W, H, dpr;

    const size = () => {
      const parent = cv.parentElement;
      W = parent.clientWidth;
      H = parent.scrollHeight || parent.clientHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = W * dpr;
      cv.height = H * dpr;
      cv.style.width = `${W}px`;
      cv.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(W / FONT_SIZE);
      const rows = Math.ceil(H / FONT_SIZE);
      drops = new Array(cols).fill(0).map(() => ({
        y: Math.random() * -rows,
        speed: 0.25 + Math.random() * 0.65,
        len: 8 + ((Math.random() * 10) | 0),
      }));
    };

    size();
    window.addEventListener("resize", size);

    let last = 0;
    const draw = (t) => {
      if (t - last > 33) {
        last = t;
        ctx.clearRect(0, 0, W, H);
        ctx.font = `${FONT_SIZE}px monospace`;
        const rows = Math.ceil(H / FONT_SIZE);
        for (let i = 0; i < cols; i++) {
          const d = drops[i];
          const headRow = Math.floor(d.y);
          for (let k = 0; k < d.len; k++) {
            const r = headRow - k;
            if (r < 0) continue;
            const yy = r * FONT_SIZE;
            const f = 1 - k / d.len; // 1 at head (bottom), 0 at tail (top)
            const g = GLYPHS[(((r * 31 + i * 7 + (k === 0 ? (t / 120) | 0 : 0)) % GLYPHS.length) + GLYPHS.length) % GLYPHS.length | 0];
            if (k === 0) {
              ctx.fillStyle = "rgba(220,242,255,1)";
            } else {
              ctx.fillStyle = `rgba(72,168,255,${(0.65 * f).toFixed(3)})`;
            }
            ctx.fillText(g, i * FONT_SIZE, yy);
          }
          d.y += d.speed;
          if (d.y - d.len > rows) {
            d.y = -(Math.random() * 12);
            d.speed = 0.25 + Math.random() * 0.65;
            d.len = 8 + ((Math.random() * 10) | 0);
          }
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener("resize", size);
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", opacity: 0.36, zIndex: 0 }}
    />
  );
}
