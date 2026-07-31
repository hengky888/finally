'use client';

import { Panel } from './Panel';
import { PlotArea } from './PlotArea';
import { PriceCell } from './PriceCell';
import { clockTime, money, signedPercent } from '@/lib/format';
import { sessionChange } from '@/lib/portfolio';
import type { SeriesPoint, TickerState } from '@/lib/types';

interface MainChartProps {
  ticker: string | null;
  state: TickerState | undefined;
  points: SeriesPoint[];
}

/** Price action for the selected ticker, accumulated live since page load. */
export function MainChart({ ticker, state, points }: MainChartProps) {
  const change = sessionChange(state);
  const span = points.length
    ? `${clockTime(points[0].t)} - ${clockTime(points[points.length - 1].t)}`
    : 'awaiting first tick';

  return (
    <Panel
      label={ticker ? `${ticker} - session` : 'Session chart'}
      readout={span}
      testId="main-chart"
      className="min-h-0 flex-1"
    >
      <div className="flex flex-none items-baseline gap-3 border-b border-hair px-3 py-2">
        <span className="label text-[17px] text-accent" data-testid="main-chart-ticker">
          {ticker ?? '--'}
        </span>
        {state ? (
          <>
            <PriceCell
              price={state.price}
              direction={state.direction}
              moveSeq={state.moveSeq}
              testId="main-chart-price"
              className="text-[17px]"
            />
            <span
              className={`num text-[12px] ${change >= 0 ? 'text-up' : 'text-down'}`}
              data-testid="main-chart-change"
            >
              {signedPercent(change)}
            </span>
          </>
        ) : (
          <span className="num text-[17px] text-dim" data-testid="main-chart-price">
            &mdash;
          </span>
        )}
        <span className="label ml-auto text-[9px] text-dim">since load</span>
      </div>

      <PlotArea
        points={points.map((point, i) => ({ x: i, y: point.p }))}
        color="var(--color-primary)"
        format={money}
        empty="No history yet. The series builds from the live stream as ticks arrive."
        testId="main-chart-plot"
      />
    </Panel>
  );
}
