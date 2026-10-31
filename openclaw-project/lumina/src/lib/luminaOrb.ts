import { finalizeFrame, paintFrame, type Dot, type OrbFrame } from '../vendor/thinking-orbs/engine/core';
import type { ModeDraw } from '../vendor/thinking-orbs/engine/types';

type Point = readonly [number, number];

// The same four cubic curves as Icons.Spark, sampled once in its 32px viewBox.
// Keep the long tips and concave shoulders: a generic star loses the brand.
const curves: readonly (readonly [Point, Point, Point, Point])[] = [
  [[16, 1], [17, 9], [19, 13], [31, 16]],
  [[31, 16], [19, 19], [17, 23], [16, 31]],
  [[16, 31], [15, 23], [13, 19], [1, 16]],
  [[1, 16], [13, 13], [15, 9], [16, 1]],
];
const outline: Point[] = curves.flatMap(([a, b, c, d]) =>
  Array.from({ length: 40 }, (_, i): Point => {
    const t = i / 40, u = 1 - t;
    return [
      u ** 3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t ** 3 * d[0],
      u ** 3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t ** 3 * d[1],
    ];
  }),
);

function inside(x: number, y: number): boolean {
  let hit = false;
  for (let i = 0, j = outline.length - 1; i < outline.length; j = i++) {
    const a = outline[i], b = outline[j];
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) hit = !hit;
  }
  return hit;
}

function particles(step: number): Point[] {
  const points: Point[] = [];
  // Centre-aligned hexagonal rows keep the small mark balanced and legible.
  for (let row = -16; row <= 16; row++) {
    const y = 16 + row * step * Math.sqrt(3) / 2;
    for (let col = -16; col <= 16; col++) {
      const x = 16 + (col + (Math.abs(row) % 2) / 2) * step;
      if (inside(x, y)) points.push([x, y]);
    }
  }
  // Exact tips anchor the silhouette even at inline size.
  return [...points, [16, 1], [31, 16], [16, 31], [1, 16]];
}
const avatar = particles(1.65);
const inline = particles(3.2);

/** A stable spark silhouette; only its breath and soft depth lighting move. */
export function frameLumina(size: number, time: number): OrbFrame {
  const points = size <= 20 ? inline : avatar;
  const breath = 1 + 0.025 * Math.sin(time * 1.6);
  const scale = size * 0.8 / 32;
  const radius = size <= 20 ? 0.52 : size * 0.0105;
  const dots: Dot[] = points.map(([x, y]) => {
    const depth = Math.cos((x - 16) / 15 * 1.1) * Math.cos((y - 16) / 15 * 1.1);
    const light = 0.5 + 0.5 * Math.sin(time * 1.6 + (x + y) * 0.1);
    return {
      x: size / 2 + (x - 16) * scale * breath,
      y: size / 2 + (y - 16) * scale * breath,
      z: depth, r: radius * (0.8 + depth * 0.2),
      white: 0.08 + (1 - depth) * 0.25 + light * 0.08,
    };
  });
  return finalizeFrame(dots, []);
}

// Reuse the library's ink and canvas painter so blends share the same material.
export const drawLumina: ModeDraw = (ctx, size, time, dark) => paintFrame(ctx, frameLumina(size, time), dark);
