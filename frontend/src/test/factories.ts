import type {
  Direction,
  PriceEnvelope,
  PriceTick,
  Portfolio,
  Position,
  TickerState,
} from '@/lib/types';

export function tick(
  ticker: string,
  price: number,
  direction: Direction = 'flat',
  previous = price,
): PriceTick {
  return {
    ticker,
    price,
    previous_price: previous,
    change: price - previous,
    change_percent: previous ? ((price - previous) / previous) * 100 : 0,
    direction,
    timestamp: 1_700_000_000,
  };
}

export function envelope(seq: number, ticks: PriceTick[]): PriceEnvelope {
  return {
    seq,
    ts: 1_700_000_000,
    prices: Object.fromEntries(ticks.map((t) => [t.ticker, t])),
  };
}

export function tickerState(overrides: Partial<TickerState> & { ticker: string }): TickerState {
  return {
    price: 100,
    direction: 'flat',
    moveSeq: 0,
    anchor: 100,
    ...overrides,
  };
}

export function position(overrides: Partial<Position> & { ticker: string }): Position {
  const base = {
    quantity: 10,
    avg_cost: 100,
    current_price: 110,
    ...overrides,
  };
  return {
    ...base,
    position_value: base.quantity * base.current_price,
    unrealized_pnl: base.quantity * (base.current_price - base.avg_cost),
    pnl_pct: (base.current_price - base.avg_cost) / base.avg_cost,
    ...overrides,
  };
}

export function portfolio(overrides: Partial<Portfolio> = {}): Portfolio {
  const positions = overrides.positions ?? [];
  const cash = overrides.cash_balance ?? 10_000;
  return {
    cash_balance: cash,
    positions,
    total_value: cash + positions.reduce((s, p) => s + p.position_value, 0),
    total_unrealized_pnl: positions.reduce((s, p) => s + p.unrealized_pnl, 0),
    ...overrides,
  };
}
