'use client';

import { useCallback, useEffect, useState } from 'react';
import { getHistory, getPortfolio, getWatchlist } from '@/lib/api';
import type { Portfolio, Snapshot, WatchlistEntry } from '@/lib/types';

const EMPTY: Portfolio = {
  cash_balance: 0,
  positions: [],
  total_value: 0,
  total_unrealized_pnl: 0,
};

export interface AccountState {
  portfolio: Portfolio;
  history: Snapshot[];
  watchlist: WatchlistEntry[];
  loaded: boolean;
  refresh: () => Promise<void>;
}

/** Server-of-record state: everything that is not a live price. */
export function usePortfolio(): AccountState {
  const [portfolio, setPortfolio] = useState<Portfolio>(EMPTY);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const [next, snapshots, tickers] = await Promise.all([
      getPortfolio(),
      getHistory(),
      getWatchlist(),
    ]);
    setPortfolio(next);
    setHistory(snapshots);
    setWatchlist(tickers);
    setLoaded(true);
  }, []);

  // Load once on mount. A failure means the backend is not up yet; the
  // connection indicator already reports that, so the terminal renders empty.
  useEffect(() => {
    void (async () => {
      await refresh().catch(() => undefined);
    })();
  }, [refresh]);

  return { portfolio, history, watchlist, loaded, refresh };
}
