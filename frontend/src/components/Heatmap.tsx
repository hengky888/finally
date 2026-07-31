'use client';

import { Panel } from './Panel';
import { signedPercent } from '@/lib/format';
import { squarify } from '@/lib/treemap';
import type { Position } from '@/lib/types';

/** P&L beyond this magnitude saturates the tile colour. */
const FULL_TINT = 0.05;

interface HeatmapProps {
  positions: Position[];
  selected: string | null;
  onSelect: (ticker: string) => void;
}

/** Positions sized by portfolio weight, coloured by unrealized P&L. */
export function Heatmap({ positions, selected, onSelect }: HeatmapProps) {
  const tiles = squarify(
    positions.map((p) => ({ key: p.ticker, value: Math.abs(p.position_value) })),
    { x: 0, y: 0, width: 100, height: 100 },
  );
  const byTicker = new Map(positions.map((p) => [p.ticker, p]));

  return (
    <Panel
      label="Exposure"
      readout={`${positions.length} held`}
      testId="heatmap"
      className="min-h-0 flex-1"
    >
      {tiles.length === 0 ? (
        <div
          className="flex flex-1 items-center justify-center px-4 text-center text-[11px] text-dim"
          data-testid="heatmap-empty"
        >
          No positions. Open one from the trade bar.
        </div>
      ) : (
        <div className="relative flex-1">
          {tiles.map((tile) => {
            const position = byTicker.get(tile.key)!;
            const gain = position.pnl_pct >= 0;
            const intensity = Math.min(Math.abs(position.pnl_pct) / FULL_TINT, 1);
            const tint = gain ? 'var(--color-up)' : 'var(--color-down)';
            const roomy = tile.width > 14 && tile.height > 18;
            return (
              <button
                key={tile.key}
                type="button"
                onClick={() => onSelect(tile.key)}
                data-testid={`heatmap-tile-${tile.key}`}
                data-pnl={gain ? 'gain' : 'loss'}
                title={`${tile.key} ${signedPercent(position.pnl_pct)}`}
                className={`absolute flex flex-col items-center justify-center overflow-hidden border p-0.5 ${
                  selected === tile.key ? 'border-accent' : 'border-void'
                }`}
                style={{
                  left: `${tile.x}%`,
                  top: `${tile.y}%`,
                  width: `${tile.width}%`,
                  height: `${tile.height}%`,
                  backgroundColor: `color-mix(in srgb, ${tint} ${12 + intensity * 58}%, var(--color-panel))`,
                }}
              >
                <span className="label text-[11px] leading-tight text-ink">{tile.key}</span>
                {roomy ? (
                  <span className="num text-[9px] leading-tight text-ink/75">
                    {signedPercent(position.pnl_pct)}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
