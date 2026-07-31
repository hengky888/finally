'use client';

import { Panel } from './Panel';
import { PlotArea } from './PlotArea';
import { money, signedPercent } from '@/lib/format';
import type { Snapshot } from '@/lib/types';

interface PnlChartProps {
  history: Snapshot[];
}

/** Total portfolio value from `portfolio_snapshots` — the one series that survives reload. */
export function PnlChart({ history }: PnlChartProps) {
  const points = history.map((snapshot) => ({
    x: Date.parse(snapshot.recorded_at),
    y: snapshot.total_value,
  }));
  const first = history[0]?.total_value ?? 0;
  const last = history[history.length - 1]?.total_value ?? 0;
  const change = first === 0 ? 0 : (last - first) / first;

  return (
    <Panel
      label="Portfolio value"
      readout={history.length ? signedPercent(change) : `${history.length} pts`}
      testId="pnl-chart"
      className="min-h-0 flex-1"
    >
      <PlotArea
        points={points}
        color="var(--color-accent)"
        format={money}
        empty="No snapshots yet. Value is recorded every 30 seconds and after each trade."
        testId="pnl-chart-plot"
      />
    </Panel>
  );
}
