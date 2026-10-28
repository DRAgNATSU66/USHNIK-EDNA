import { useEffect, useRef } from "react";

const WIDTH = 430;
const HEIGHT = 500;

function rnd(i) {
  const x = Math.sin(i * 127.1) * 43758.5453;
  return x - Math.floor(x);
}

export default function HelixCanvas() {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    cv.width = WIDTH * dpr;
    cv.height = HEIGHT * dpr;
    ctx.scale(dpr, dpr);

    const N = 170, R = 100, cx = WIDTH / 2, coils = 2.6, PER = 0.55;
    const WEB = [];
    for (let i = 0; i < 46; i++) {
      WEB.push({ h: rnd(i * 3), ang: rnd(i * 5 + 1) * Math.PI * 2, rad: 1.15 + rnd(i * 7 + 2) * 0.75, seed: i });
    }
    const SAT = 4;

    const draw = (t) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.translate(WIDTH / 2, HEIGHT / 2);
      ctx.rotate(Math.PI / 6);
      ctx.scale(0.86, 0.86);
      ctx.translate(-WIDTH / 2, -HEIGHT / 2);
      ctx.globalCompositeOperation = "lighter";
      const rot = t * 0.00085;

      const pt = (i, phase, roff, yoff) => {
        const y = 20 + (i / (N - 1)) * (HEIGHT - 40) + (yoff || 0);
        const a = (i / (N - 1)) * coils * Math.PI * 2 + rot + phase;
        const rr = R * (1 + (roff || 0));
        const z = Math.cos(a);
        const persp = 1 + z * 0.001 * PER * 220;
        return { x: cx + Math.sin(a) * rr * (0.9 + 0.1 * persp), y, z, s: 0.75 + ((z + 1) / 2) * 0.55 };
      };

      for (let i = 3; i < N - 3; i += 5) {
        const p1 = pt(i, 0), p2 = pt(i, Math.PI);
        const d = (p1.z + p2.z + 2) / 4;
        ctx.strokeStyle = `rgba(70,180,225,${0.05 + 0.14 * d})`;
        ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
        const steps = 5;
        for (let k = 1; k < steps; k++) {
          const fx = p1.x + (p2.x - p1.x) * (k / steps), fy = p1.y + (p2.y - p1.y) * (k / steps);
          const a = 0.10 + 0.30 * d * (0.5 + rnd(i * 11 + k) * 0.5);
          ctx.fillStyle = `rgba(110,205,240,${a})`;
          ctx.beginPath(); ctx.arc(fx, fy, 0.9 + d * 0.9, 0, 7); ctx.fill();
        }
      }

      ctx.lineWidth = 0.5;
      for (let i = 0; i < N - 8; i += 4) {
        const s = rnd(i * 5) > 0.5 ? 0 : Math.PI;
        const p1 = pt(i, s), p2 = pt(i + 5 + Math.floor(rnd(i) * 6), s);
        const d = (p1.z + p2.z + 2) / 4;
        if (d < 0.45) continue;
        ctx.strokeStyle = `rgba(120,215,250,${0.05 + 0.10 * d})`;
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
      }

      const webP = WEB.map((w) => {
        const y = 20 + w.h * (HEIGHT - 40);
        const a = w.h * coils * Math.PI * 2 + rot + w.ang;
        const z = Math.cos(a) * Math.min(w.rad, 1.4);
        return { x: cx + Math.sin(a) * R * w.rad, y, z, seed: w.seed };
      });
      for (let i = 0; i < webP.length; i++) {
        const w1 = webP[i];
        const d1 = (w1.z + 1.4) / 2.8;
        let links = 0;
        for (let j = 0; j < webP.length && links < 2; j++) {
          if (j === i) continue;
          const w2 = webP[j];
          const dx = w1.x - w2.x, dy = w1.y - w2.y;
          const dist = Math.hypot(dx, dy);
          if (dist < 95) {
            const a = (0.03 + 0.09 * d1) * (1 - dist / 95);
            ctx.strokeStyle = `rgba(140,220,250,${a})`;
            ctx.lineWidth = 0.5;
            ctx.beginPath(); ctx.moveTo(w1.x, w1.y); ctx.lineTo(w2.x, w2.y); ctx.stroke();
            links++;
          }
        }
        const si = Math.round(((w1.y - 20) / (HEIGHT - 40)) * (N - 1));
        const sp = pt(Math.max(0, Math.min(N - 1, si)), rnd(w1.seed) > 0.5 ? 0 : Math.PI);
        const td = Math.hypot(w1.x - sp.x, w1.y - sp.y);
        if (td < 130) {
          ctx.strokeStyle = `rgba(110,205,245,${0.04 + 0.10 * d1 * (1 - td / 130)})`;
          ctx.lineWidth = 0.45;
          ctx.beginPath(); ctx.moveTo(w1.x, w1.y); ctx.lineTo(sp.x, sp.y); ctx.stroke();
        }
        const deep = rnd(w1.seed * 9) > 0.6;
        const col = deep ? "60,110,235" : "120,215,250";
        const nr = (deep ? 1.6 : 1.0) * (0.5 + d1);
        const ng = ctx.createRadialGradient(w1.x, w1.y, 0, w1.x, w1.y, nr * 3);
        ng.addColorStop(0, `rgba(${col},${0.25 + d1 * 0.55})`);
        ng.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = ng;
        ctx.beginPath(); ctx.arc(w1.x, w1.y, nr * 3, 0, 7); ctx.fill();
      }
      for (let i = 0; i < webP.length - 2; i += 5) {
        const a1 = webP[i], a2 = webP[i + 1], a3 = webP[i + 2];
        const dAvg = (a1.z + a2.z + a3.z + 4.2) / 8.4;
        if (dAvg < 0.55) continue;
        if (Math.hypot(a1.x - a2.x, a1.y - a2.y) > 110 || Math.hypot(a1.x - a3.x, a1.y - a3.y) > 110) continue;
        ctx.fillStyle = `rgba(100,200,245,${0.025 + 0.035 * dAvg})`;
        ctx.beginPath(); ctx.moveTo(a1.x, a1.y); ctx.lineTo(a2.x, a2.y); ctx.lineTo(a3.x, a3.y); ctx.closePath(); ctx.fill();
      }

      for (let s = 0; s < 2; s++) {
        const phase = s * Math.PI;
        for (let pass = 0; pass < 2; pass++) {
          for (let i = 0; i < N; i++) {
            const p = pt(i, phase);
            const depth = (p.z + 1) / 2;
            if (pass === 0 ? depth > 0.5 : depth <= 0.5) continue;
            const hue = s === 0 ? "155,228,255" : "75,195,245";
            const r = (1.0 + depth * 2.4) * p.s;
            const alpha = 0.16 + depth * 0.8;
            const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.4);
            g.addColorStop(0, `rgba(${hue},${alpha})`);
            g.addColorStop(0.35, `rgba(${hue},${alpha * 0.4})`);
            g.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(p.x, p.y, r * 3.4, 0, 7); ctx.fill();
            ctx.fillStyle = `rgba(225,248,255,${alpha * 0.9})`;
            ctx.beginPath(); ctx.arc(p.x, p.y, r * 0.5, 0, 7); ctx.fill();
            for (let k = 0; k < SAT; k++) {
              const seed = i * 13 + k * 31 + s * 97;
              const ox = (rnd(seed) - 0.5) * 26 * (0.4 + depth);
              const oy = (rnd(seed + 1) - 0.5) * 14;
              const sa = (0.05 + rnd(seed + 2) * 0.3) * (0.3 + depth * 0.7);
              ctx.fillStyle = `rgba(${hue},${sa})`;
              ctx.beginPath(); ctx.arc(p.x + ox, p.y + oy, 0.5 + rnd(seed + 3) * 1.3 * p.s, 0, 7); ctx.fill();
            }
            if (rnd(i * 3 + s * 7) > 0.94 && depth > 0.6) {
              const fr = 20 + rnd(i) * 14;
              const pulse = 0.7 + 0.3 * Math.sin(t * 0.002 + i);
              const fg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, fr);
              fg.addColorStop(0, `rgba(210,245,255,${0.6 * depth * pulse})`);
              fg.addColorStop(0.25, `rgba(90,200,250,${0.28 * depth * pulse})`);
              fg.addColorStop(1, "rgba(0,0,0,0)");
              ctx.fillStyle = fg;
              ctx.beginPath(); ctx.arc(p.x, p.y, fr, 0, 7); ctx.fill();
              ctx.strokeStyle = `rgba(230,250,255,${0.5 * depth * pulse})`;
              ctx.lineWidth = 0.7;
              const sl = 7 * pulse;
              ctx.beginPath();
              ctx.moveTo(p.x - sl, p.y); ctx.lineTo(p.x + sl, p.y);
              ctx.moveTo(p.x, p.y - sl); ctx.lineTo(p.x, p.y + sl);
              ctx.stroke();
            }
          }
        }
      }

      for (let i = 0; i < 110; i++) {
        const layer = i < 60 ? 0.4 : 1;
        const dx = (rnd(i) * WIDTH + t * 0.002 * layer * (rnd(i + 7) - 0.5) * 10 + WIDTH) % WIDTH;
        const dy = (rnd(i + 60) * HEIGHT + t * 0.005 * layer * (4 + rnd(i) * 10)) % HEIGHT;
        const tw = 0.5 + 0.5 * Math.sin(t * 0.003 + i * 2.7);
        const a = (0.04 + rnd(i + 120) * 0.2) * layer * tw;
        ctx.fillStyle = `rgba(130,215,245,${a})`;
        ctx.beginPath(); ctx.arc(dx, dy, (0.5 + rnd(i + 30) * 1.2) * layer, 0, 7); ctx.fill();
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: `${WIDTH}px`, height: `${HEIGHT}px`, display: "block", margin: "-30px 0", maxWidth: "100%" }}
    />
  );
}
