/**
 * Valuation math, mirroring PLAN.md section 8 exactly so the header can revalue
 * on every tick without waiting for the backend to agree.
 */

import type { Portfolio, Position, TickerState } from './types';

export function positionValue(quantity: number, price: number): number {
  return quantity * price;
}

export function unrealizedPnl(quantity: number, price: number, avgCost: number): number {
  return quantity * (price - avgCost);
}

export function pnlPct(price: number, avgCost: number): number {
  return avgCost === 0 ? 0 : (price - avgCost) / avgCost;
}

/** Re-price one position against the live stream, falling back to the served price. */
export function revaluePosition(
  position: Position,
  live: Record<string, TickerState>,
): Position {
  const price = live[position.ticker]?.price ?? position.current_price;
  return {
    ...position,
    current_price: price,
    position_value: positionValue(position.quantity, price),
    unrealized_pnl: unrealizedPnl(position.quantity, price, position.avg_cost),
    pnl_pct: pnlPct(price, position.avg_cost),
  };
}

/** Re-price a whole portfolio: total_value = cash + sum(position_value). */
export function revaluePortfolio(
  portfolio: Portfolio,
  live: Record<string, TickerState>,
): Portfolio {
  const positions = portfolio.positions.map((p) => revaluePosition(p, live));
  const invested = positions.reduce((sum, p) => sum + p.position_value, 0);
  return {
    ...portfolio,
    positions,
    total_value: portfolio.cash_balance + invested,
    total_unrealized_pnl: positions.reduce((sum, p) => sum + p.unrealized_pnl, 0),
  };
}

/** Share of invested capital, used to size the heatmap tiles. */
export function weights(positions: Position[]): Record<string, number> {
  const invested = positions.reduce((sum, p) => sum + Math.abs(p.position_value), 0);
  if (invested === 0) return Object.fromEntries(positions.map((p) => [p.ticker, 0]));
  return Object.fromEntries(
    positions.map((p) => [p.ticker, Math.abs(p.position_value) / invested]),
  );
}

/** Session change for a watchlist row: move since the first tick after load. */
export function sessionChange(state: TickerState | undefined): number {
  if (!state || state.anchor === 0) return 0;
  return (state.price - state.anchor) / state.anchor;
}
