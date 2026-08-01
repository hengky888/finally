/** Squarified treemap layout for the portfolio heatmap. */

export interface TreemapItem {
  key: string;
  value: number;
}

export interface Tile {
  key: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Lay out items in `rect`, largest first, keeping tiles close to square.
 * Values are treated as relative weights; non-positive values are dropped.
 */
export function squarify(items: TreemapItem[], rect: Rect): Tile[] {
  const usable = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  const total = usable.reduce((sum, i) => sum + i.value, 0);
  if (total === 0 || rect.width <= 0 || rect.height <= 0) return [];

  const area = rect.width * rect.height;
  const scaled = usable.map((i) => ({ key: i.key, area: (i.value / total) * area }));

  const tiles: Tile[] = [];
  let free: Rect = { ...rect };
  let row: typeof scaled = [];

  const shortest = () => Math.min(free.width, free.height);

  for (const item of scaled) {
    if (row.length === 0 || worst([...row, item], shortest()) <= worst(row, shortest())) {
      row.push(item);
    } else {
      free = placeRow(row, free, tiles);
      row = [item];
    }
  }
  if (row.length) placeRow(row, free, tiles);

  return tiles;
}

/** Aspect ratio of the worst tile in a candidate row — the squarify heuristic. */
function worst(row: { area: number }[], side: number): number {
  if (row.length === 0 || side === 0) return Infinity;
  const sum = row.reduce((s, i) => s + i.area, 0);
  const max = Math.max(...row.map((i) => i.area));
  const min = Math.min(...row.map((i) => i.area));
  const side2 = side * side;
  const sum2 = sum * sum;
  return Math.max((side2 * max) / sum2, sum2 / (side2 * min));
}

/** Emit one row along the shorter edge and return the remaining free rectangle. */
function placeRow(row: { key: string; area: number }[], free: Rect, out: Tile[]): Rect {
  const sum = row.reduce((s, i) => s + i.area, 0);
  const horizontal = free.width >= free.height;
  const thickness = horizontal ? sum / free.height : sum / free.width;

  let offset = 0;
  for (const item of row) {
    const length = (item.area / sum) * (horizontal ? free.height : free.width);
    out.push(
      horizontal
        ? { key: item.key, x: free.x, y: free.y + offset, width: thickness, height: length }
        : { key: item.key, x: free.x + offset, y: free.y, width: length, height: thickness },
    );
    offset += length;
  }

  return horizontal
    ? { x: free.x + thickness, y: free.y, width: free.width - thickness, height: free.height }
    : { x: free.x, y: free.y + thickness, width: free.width, height: free.height - thickness };
}
