import { ApiError, executeTrade, getHistory, normalizeWatchlist } from './api';

describe('normalizeWatchlist', () => {
  it('accepts a bare array of rows', () => {
    expect(normalizeWatchlist([{ ticker: 'AAPL', price: 190 }])).toEqual([
      { ticker: 'AAPL', price: 190 },
    ]);
  });

  it('accepts a wrapped array', () => {
    expect(normalizeWatchlist({ watchlist: [{ ticker: 'AAPL', price: 190 }] })).toEqual([
      { ticker: 'AAPL', price: 190 },
    ]);
    expect(normalizeWatchlist({ tickers: [{ ticker: 'TSLA', price: 250 }] })).toEqual([
      { ticker: 'TSLA', price: 250 },
    ]);
  });

  it('accepts plain symbols and marks them unpriced', () => {
    expect(normalizeWatchlist(['AAPL', 'TSLA'])).toEqual([
      { ticker: 'AAPL', price: null },
      { ticker: 'TSLA', price: null },
    ]);
  });

  it('treats a missing price as unpriced', () => {
    expect(normalizeWatchlist([{ ticker: 'PYPL' }])).toEqual([{ ticker: 'PYPL', price: null }]);
  });

  it('returns nothing for an empty response', () => {
    expect(normalizeWatchlist({})).toEqual([]);
  });
});

describe('request handling', () => {
  const mockFetch = (body: unknown, ok = true, status = 200) => {
    global.fetch = jest.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(body),
    }) as unknown as typeof fetch;
  };

  it('unwraps a wrapped snapshot list', async () => {
    mockFetch({ snapshots: [{ total_value: 10_000, recorded_at: '2026-07-31T00:00:00' }] });

    await expect(getHistory()).resolves.toHaveLength(1);
  });

  it('raises the backend rejection text, not the status code', async () => {
    mockFetch({ detail: 'Insufficient cash to buy 10 TSLA' }, false, 400);

    await expect(executeTrade({ ticker: 'TSLA', quantity: 10, side: 'buy' })).rejects.toThrow(
      new ApiError('Insufficient cash to buy 10 TSLA'),
    );
  });

  it('falls back to the status code when there is no detail', async () => {
    mockFetch(null, false, 500);

    await expect(executeTrade({ ticker: 'TSLA', quantity: 1, side: 'buy' })).rejects.toThrow(
      'Request failed (500)',
    );
  });
});
