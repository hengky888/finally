'use client';

import { Panel } from './Panel';
import { money, quantity, signedMoney, signedPercent } from '@/lib/format';
import type { Position } from '@/lib/types';

interface PositionsTableProps {
  positions: Position[];
  totalPnl: number;
  selected: string | null;
  onSelect: (ticker: string) => void;
}

const COLUMNS = ['Symbol', 'Qty', 'Avg cost', 'Last', 'Unrealized', 'Change'];

export function PositionsTable({
  positions,
  totalPnl,
  selected,
  onSelect,
}: PositionsTableProps) {
  return (
    <Panel
      label="Positions"
      readout={
        <span className={totalPnl >= 0 ? 'text-up' : 'text-down'} data-testid="positions-total-pnl">
          {signedMoney(totalPnl)}
        </span>
      }
      testId="positions-panel"
      className="min-h-0 flex-1"
    >
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse" data-testid="positions-table">
          <thead className="sticky top-0 bg-panel">
            <tr className="border-b border-hair">
              {COLUMNS.map((column, i) => (
                <th
                  key={column}
                  className={`label px-3 py-1.5 text-[9px] font-semibold text-dim ${
                    i === 0 ? 'text-left' : 'text-right'
                  }`}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const gain = position.unrealized_pnl >= 0;
              return (
                <tr
                  key={position.ticker}
                  onClick={() => onSelect(position.ticker)}
                  data-testid={`positions-row-${position.ticker}`}
                  className={`cursor-pointer border-b border-hair/60 transition-colors ${
                    selected === position.ticker ? 'bg-raise/60' : 'hover:bg-raise/30'
                  }`}
                >
                  <td className="label px-3 py-1.5 text-[12px] text-ink">{position.ticker}</td>
                  <td
                    className="num px-3 py-1.5 text-right text-[12px]"
                    data-testid={`position-qty-${position.ticker}`}
                  >
                    {quantity(position.quantity)}
                  </td>
                  <td
                    className="num px-3 py-1.5 text-right text-[12px] text-muted"
                    data-testid={`position-avg-cost-${position.ticker}`}
                  >
                    {money(position.avg_cost)}
                  </td>
                  <td
                    className="num px-3 py-1.5 text-right text-[12px]"
                    data-testid={`position-price-${position.ticker}`}
                  >
                    {money(position.current_price)}
                  </td>
                  <td
                    className={`num px-3 py-1.5 text-right text-[12px] ${gain ? 'text-up' : 'text-down'}`}
                    data-testid={`position-pnl-${position.ticker}`}
                  >
                    {signedMoney(position.unrealized_pnl)}
                  </td>
                  <td
                    className={`num px-3 py-1.5 text-right text-[12px] ${gain ? 'text-up' : 'text-down'}`}
                    data-testid={`position-pnl-pct-${position.ticker}`}
                  >
                    {signedPercent(position.pnl_pct)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {positions.length === 0 ? (
          <p className="px-3 py-4 text-[11px] text-dim" data-testid="positions-empty">
            No open positions. Buy something from the trade bar below.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
