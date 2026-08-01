/**
 * Chart geometry. The terminal draws its own SVG rather than pulling in a chart
 * library, so grids, ticks and line weights share one visual language.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  width: number;
  height: number;
  padTop?: number;
  padBottom?: number;
  padLeft?: number;
  padRight?: number;
}

export interface Plot {
  line: string;
  area: string;
  min: number;
  max: number;
  last: Point | null;
  project: (point: Point) => Point;
}

/** Map data points into an SVG viewBox and build the line and fill paths. */
export function plot(points: Point[], box: Box): Plot {
  const left = box.padLeft ?? 0;
  const right = box.width - (box.padRight ?? 0);
  const top = box.padTop ?? 0;
  const bottom = box.height - (box.padBottom ?? 0);

  const ys = points.map((p) => p.y);
  const rawMin = ys.length ? Math.min(...ys) : 0;
  const rawMax = ys.length ? Math.max(...ys) : 0;
  // A dead-flat series would divide by zero; give it a hairline band instead.
  const span = rawMax - rawMin;
  const pad = span === 0 ? Math.max(Math.abs(rawMax) * 0.001, 0.01) : span * 0.08;
  const min = rawMin - pad;
  const max = rawMax + pad;

  const xs = points.map((p) => p.x);
  const xMin = xs.length ? Math.min(...xs) : 0;
  const xMax = xs.length ? Math.max(...xs) : 1;
  const xSpan = xMax - xMin || 1;

  const project = (point: Point): Point => ({
    x: left + ((point.x - xMin) / xSpan) * (right - left),
    y: bottom - ((point.y - min) / (max - min)) * (bottom - top),
  });

  if (points.length === 0) {
    return { line: '', area: '', min, max, last: null, project };
  }

  const projected = points.map(project);
  const line = projected.map((p, i) => `${i === 0 ? 'M' : 'L'}${round(p.x)} ${round(p.y)}`).join(' ');
  const first = projected[0];
  const final = projected[projected.length - 1];
  const area = `${line} L${round(final.x)} ${round(bottom)} L${round(first.x)} ${round(bottom)} Z`;

  return { line, area, min, max, last: final, project };
}

/** Evenly spaced values between min and max, for gridlines and axis labels. */
export function ticks(min: number, max: number, count: number): number[] {
  if (count < 2) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
