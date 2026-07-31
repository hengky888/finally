import { plot, ticks, type Point } from '@/lib/chart';

const VIEW_W = 1000;
const VIEW_H = 300;
const GRID_LINES = 5;

interface PlotAreaProps {
  points: Point[];
  color: string;
  /** Formats the right-hand price scale. */
  format: (value: number) => string;
  empty: string;
  testId: string;
}

/**
 * Shared plot surface: hairline grid in a stretched SVG, scale labels in HTML so
 * type never distorts with the container.
 */
export function PlotArea({ points, color, format, empty, testId }: PlotAreaProps) {
  const { line, area, min, max, last } = plot(points, {
    width: VIEW_W,
    height: VIEW_H,
    padTop: 8,
    padBottom: 8,
  });

  if (!line) {
    return (
      <div
        className="flex flex-1 items-center justify-center px-4 text-center text-[11px] text-dim"
        data-testid={`${testId}-empty`}
      >
        {empty}
      </div>
    );
  }

  // Grid lines and scale labels share one projection so they never drift apart.
  const scale = ticks(min, max, GRID_LINES).reverse();
  const gridY = (i: number) => 8 + ((VIEW_H - 16) / (GRID_LINES - 1)) * i;

  return (
    <div className="relative flex-1" data-testid={testId} data-points={points.length}>
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {scale.map((_, i) => (
          <line
            key={i}
            x1={0}
            x2={VIEW_W}
            y1={gridY(i)}
            y2={gridY(i)}
            stroke="var(--color-hair)"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <path d={area} fill={color} opacity={0.1} />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
        {last ? (
          <line
            x1={0}
            x2={VIEW_W}
            y1={last.y}
            y2={last.y}
            stroke={color}
            strokeDasharray="3 4"
            opacity={0.5}
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>

      <div className="pointer-events-none absolute inset-y-0 right-0 w-16 border-l border-hair bg-panel/85">
        {scale.map((value, i) => (
          <span
            key={i}
            className="num absolute right-1 -translate-y-1/2 text-[9px] text-dim"
            style={{ top: `${(gridY(i) / VIEW_H) * 100}%` }}
          >
            {format(value)}
          </span>
        ))}
        {last ? (
          <span
            className="num absolute right-1 -translate-y-1/2 px-1 text-[9px] font-medium text-void"
            style={{ top: `${(last.y / VIEW_H) * 100}%`, backgroundColor: color }}
          >
            {format(points[points.length - 1].y)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
