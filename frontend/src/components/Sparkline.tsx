import { plot } from '@/lib/chart';
import type { SeriesPoint } from '@/lib/types';

interface SparklineProps {
  points: SeriesPoint[];
  up: boolean;
  width?: number;
  height?: number;
  testId?: string;
}

/** Session price action beside a watchlist row, accumulated from the stream. */
export function Sparkline({ points, up, width = 76, height = 18, testId }: SparklineProps) {
  const data = points.map((point, i) => ({ x: i, y: point.p }));
  const { line, area, last } = plot(data, { width, height, padTop: 2, padBottom: 2 });
  const stroke = up ? 'var(--color-up)' : 'var(--color-down)';

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      data-testid={testId}
      data-points={points.length}
    >
      {line ? (
        <>
          <path d={area} fill={stroke} opacity={0.12} />
          <path d={line} fill="none" stroke={stroke} strokeWidth={1} />
          {last ? <circle cx={last.x} cy={last.y} r={1.5} fill={stroke} /> : null}
        </>
      ) : (
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke="var(--color-line)"
          strokeDasharray="2 3"
        />
      )}
    </svg>
  );
}
