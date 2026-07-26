import { useEffect, useRef } from "react";
import { useReducedMotion } from "motion/react";

/* Monochrome wireframe globe with route arcs only for shortlisted countries.
   Canvas 2D orthographic projection — restrained, no textures. */
export interface GlobePoint { lat: number; lng: number; active: boolean; }

const DHAKA = { lat: 23.81, lng: 90.41 };

export function Globe({ theme, targets }: { theme: "light" | "dark"; targets: GlobePoint[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let rot = 0;

    // Random "signal" arcs fired from Dhaka to a random point, one at a time.
    interface Arc { lat: number; lng: number; born: number; }
    let arc: Arc | null = null;
    let nextSpawn = performance.now() + 400;
    const ARC_LIFE = 2800; // ms: draw → hold → fade
    const line = theme === "dark" ? "rgba(236,231,219,0.18)" : "rgba(26,28,26,0.16)";
    const accent = theme === "dark" ? "#4ba38c" : "#0f3d33";
    const gold = theme === "dark" ? "#cba85c" : "#9a7b32";

    function size() {
      const rect = canvas!.getBoundingClientRect();
      canvas!.width = rect.width * dpr;
      canvas!.height = rect.height * dpr;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w: rect.width, h: rect.height };
    }

    function project(lat: number, lng: number, cx: number, cy: number, r: number, rotation: number) {
      const phi = (lat * Math.PI) / 180;
      const lam = ((lng + rotation) * Math.PI) / 180;
      const x = Math.cos(phi) * Math.sin(lam);
      const y = Math.sin(phi);
      const z = Math.cos(phi) * Math.cos(lam);
      return { x: cx + x * r, y: cy - y * r, visible: z > -0.1, z };
    }

    function draw() {
      const now = performance.now();
      const { w, h } = size();
      const cx = w / 2;
      const cy = h / 2;
      const r = Math.min(w, h) / 2 - 12;
      ctx!.clearRect(0, 0, w, h);

      // spawn a fresh random arc once the previous has finished
      if (!arc && now >= nextSpawn) {
        arc = { lat: Math.random() * 120 - 60, lng: Math.random() * 360 - 180, born: now };
      }

      // sphere outline
      ctx!.strokeStyle = line;
      ctx!.lineWidth = 1;
      ctx!.beginPath();
      ctx!.arc(cx, cy, r, 0, Math.PI * 2);
      ctx!.stroke();

      // meridians + parallels
      for (let lng = -180; lng < 180; lng += 30) {
        ctx!.beginPath();
        let started = false;
        for (let lat = -90; lat <= 90; lat += 4) {
          const p = project(lat, lng, cx, cy, r, rot);
          if (p.visible) { started ? ctx!.lineTo(p.x, p.y) : ctx!.moveTo(p.x, p.y); started = true; }
          else started = false;
        }
        ctx!.stroke();
      }
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx!.beginPath();
        let started = false;
        for (let lng = -180; lng <= 180; lng += 4) {
          const p = project(lat, lng, cx, cy, r, rot);
          if (p.visible) { started ? ctx!.lineTo(p.x, p.y) : ctx!.moveTo(p.x, p.y); started = true; }
          else started = false;
        }
        ctx!.stroke();
      }

      // Dhaka origin
      const o = project(DHAKA.lat, DHAKA.lng, cx, cy, r, rot);
      if (o.visible) {
        ctx!.fillStyle = accent;
        ctx!.beginPath();
        ctx!.arc(o.x, o.y, 3, 0, Math.PI * 2);
        ctx!.fill();
      }

      // route arcs to active targets
      targets.filter((tt) => tt.active).forEach((tt) => {
        const d = project(tt.lat, tt.lng, cx, cy, r, rot);
        if (o.visible && d.visible) {
          const mx = (o.x + d.x) / 2;
          const my = (o.y + d.y) / 2 - r * 0.28;
          ctx!.beginPath();
          ctx!.moveTo(o.x, o.y);
          ctx!.quadraticCurveTo(mx, my, d.x, d.y);
          ctx!.strokeStyle = gold;
          ctx!.lineWidth = 1.5;
          ctx!.stroke();
        }
        if (d.visible) {
          ctx!.fillStyle = gold;
          ctx!.beginPath();
          ctx!.arc(d.x, d.y, 3, 0, Math.PI * 2);
          ctx!.fill();
        }
      });

      // random signal arc — draws out, holds, then fades before the next fires
      if (arc) {
        const age = now - arc.born;
        const life = age / ARC_LIFE;
        if (life >= 1) {
          arc = null;
          nextSpawn = now + 500 + Math.random() * 1400;
        } else {
          const grow = Math.min(1, life / 0.4); // draw in first 40%
          const alpha = life < 0.7 ? 1 : 1 - (life - 0.7) / 0.3;
          const d = project(arc.lat, arc.lng, cx, cy, r, rot);
          if (o.visible && d.visible) {
            const mx = (o.x + d.x) / 2;
            const my = (o.y + d.y) / 2 - r * 0.34;
            ctx!.strokeStyle = accent;
            ctx!.globalAlpha = alpha;
            ctx!.lineWidth = 1.25;
            ctx!.beginPath();
            ctx!.moveTo(o.x, o.y);
            const steps = 40;
            for (let i = 1; i <= steps * grow; i++) {
              const tt = i / steps;
              const it = 1 - tt;
              const px = it * it * o.x + 2 * it * tt * mx + tt * tt * d.x;
              const py = it * it * o.y + 2 * it * tt * my + tt * tt * d.y;
              ctx!.lineTo(px, py);
            }
            ctx!.stroke();
            if (grow >= 1) {
              ctx!.fillStyle = accent;
              ctx!.beginPath();
              ctx!.arc(d.x, d.y, 2.5, 0, Math.PI * 2);
              ctx!.fill();
            }
            ctx!.globalAlpha = 1;
          }
        }
      }

      if (!reduce) { rot += 0.12; raf = requestAnimationFrame(draw); }
    }

    draw();
    window.addEventListener("resize", draw);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", draw); };
  }, [theme, targets, reduce]);

  return <canvas ref={ref} className="h-full w-full" aria-hidden />;
}
