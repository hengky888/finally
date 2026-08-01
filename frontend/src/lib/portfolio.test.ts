import {
  pnlPct,
  positionValue,
  revaluePortfolio,
  revaluePosition,
  sessionChange,
  unrealizedPnl,
  weights,
} from './portfolio';
import { portfolio, position, tickerState } from '@/test/factories';

describe('valuation formulas', () => {
  it('matches the backend definitions', () => {
    expect(positionValue(10, 190)).toBe(1900);
    expect(unrealizedPnl(10, 190, 180)).toBe(100);
    expect(pnlPct(190, 180)).toBeCloseTo(0.055556, 6);
  });

  it('reports a loss as a negative P&L', () => {
    expect(unrealizedPnl(5, 90, 100)).toBe(-50);
    expect(pnlPct(90, 100)).toBeCloseTo(-0.1, 10);
  });

  it('returns zero percent when there is no cost basis', () => {
    expect(pnlPct(50, 0)).toBe(0);
  });
});

describe('revaluePosition', () => {
  it('reprices against the live stream', () => {
    const revalued = revaluePosition(
      position({ ticker: 'AAPL', quantity: 4, avg_cost: 100, current_price: 100 }),
      { AAPL: tickerState({ ticker: 'AAPL', price: 125 }) },
    );

    expect(revalued.current_price).toBe(125);
    expect(revalued.position_value).toBe(500);
    expect(revalued.unrealized_pnl).toBe(100);
    expect(revalued.pnl_pct).toBeCloseTo(0.25, 10);
  });

  it('falls back to the served price when the ticker has no live quote', () => {
    const revalued = revaluePosition(
      position({ ticker: 'JPM', quantity: 2, avg_cost: 100, current_price: 150 }),
      {},
    );

    expect(revalued.position_value).toBe(300);
  });
});

describe('revaluePortfolio', () => {
  it('sets total value to cash plus position value', () => {
    const revalued = revaluePortfolio(
      portfolio({
        cash_balance: 5000,
        positions: [
          position({ ticker: 'AAPL', quantity: 10, avg_cost: 100, current_price: 100 }),
          position({ ticker: 'TSLA', quantity: 2, avg_cost: 200, current_price: 200 }),
        ],
      }),
      {
        AAPL: tickerState({ ticker: 'AAPL', price: 110 }),
        TSLA: tickerState({ ticker: 'TSLA', price: 190 }),
      },
    );

    expect(revalued.total_value).toBe(5000 + 1100 + 380);
    expect(revalued.total_unrealized_pnl).toBe(100 - 20);
  });

  it('leaves an empty portfolio worth its cash', () => {
    const revalued = revaluePortfolio(portfolio({ cash_balance: 10_000 }), {});

    expect(revalued.total_value).toBe(10_000);
    expect(revalued.total_unrealized_pnl).toBe(0);
  });
});

describe('weights', () => {
  it('splits exposure by position value', () => {
    const result = weights([
      position({ ticker: 'AAPL', quantity: 10, current_price: 100 }),
      position({ ticker: 'TSLA', quantity: 10, current_price: 300 }),
    ]);

    expect(result.AAPL).toBeCloseTo(0.25, 10);
    expect(result.TSLA).toBeCloseTo(0.75, 10);
  });

  it('gives every position zero weight when nothing is invested', () => {
    expect(weights([position({ ticker: 'AAPL', quantity: 0, current_price: 0 })])).toEqual({
      AAPL: 0,
    });
  });
});

describe('sessionChange', () => {
  it('measures the move since the first tick of the session', () => {
    expect(sessionChange(tickerState({ ticker: 'AAPL', price: 110, anchor: 100 }))).toBeCloseTo(
      0.1,
      10,
    );
  });

  it('is flat for a ticker with no quote yet', () => {
    expect(sessionChange(undefined)).toBe(0);
  });
});
