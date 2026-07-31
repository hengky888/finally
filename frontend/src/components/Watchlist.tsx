'use client';

import { useState, type FormEvent } from 'react';
import { Panel } from './Panel';
import { PriceCell } from './PriceCell';
import { Sparkline } from './Sparkline';
import { signedPercent } from '@/lib/format';
import { sessionChange } from '@/lib/portfolio';
import type { SeriesPoint, TickerState, WatchlistEntry } from '@/lib/types';

interface WatchlistProps {
  entries: WatchlistEntry[];
  tickers: Record<string, TickerState>;
  series: Record<string, SeriesPoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

export function Watchlist({
  entries,
  tickers,
  series,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistProps) {
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ticker = draft.trim().toUpperCase();
    if (!ticker) return;
    setError(null);
    try {
      await onAdd(ticker);
      setDraft('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not add that ticker.');
    }
  }

  return (
    <Panel label="Watchlist" readout={`${entries.length}`} testId="watchlist" className="h-full">
      <div className="flex-1 overflow-y-auto">
        {entries.map((entry) => {
          const state = tickers[entry.ticker];
          const change = sessionChange(state);
          const active = selected === entry.ticker;
          return (
            <div
              key={entry.ticker}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(entry.ticker)}
              onKeyDown={(event) => event.key === 'Enter' && onSelect(entry.ticker)}
              data-testid={`watchlist-row-${entry.ticker}`}
              data-selected={active}
              className={`group grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-2 border-l-2 px-2.5 py-1.5 transition-colors ${
                active
                  ? 'border-l-accent bg-raise/60'
                  : 'border-l-transparent hover:bg-raise/30'
              }`}
            >
              <div className="flex items-baseline gap-2 overflow-hidden">
                <span
                  className="label text-[13px] text-ink"
                  data-testid={`watchlist-ticker-${entry.ticker}`}
                >
                  {entry.ticker}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${entry.ticker}`}
                  data-testid={`watchlist-remove-${entry.ticker}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void onRemove(entry.ticker);
                  }}
                  className="text-[11px] leading-none text-dim opacity-0 transition-opacity group-hover:opacity-100 hover:text-down focus-visible:opacity-100"
                >
                  &times;
                </button>
              </div>

              <Sparkline
                points={series[entry.ticker] ?? []}
                up={change >= 0}
                testId={`watchlist-sparkline-${entry.ticker}`}
              />

              <div className="col-span-2 flex items-baseline justify-between">
                {state ? (
                  <PriceCell
                    price={state.price}
                    direction={state.direction}
                    moveSeq={state.moveSeq}
                    testId={`watchlist-price-${entry.ticker}`}
                    className="text-[13px]"
                  />
                ) : (
                  <span
                    className="num text-[13px] text-dim"
                    data-testid={`watchlist-price-${entry.ticker}`}
                  >
                    &mdash;
                  </span>
                )}
                <span
                  className={`num text-[11px] ${change >= 0 ? 'text-up' : 'text-down'}`}
                  data-testid={`watchlist-change-${entry.ticker}`}
                >
                  {state ? signedPercent(change) : ''}
                </span>
              </div>
            </div>
          );
        })}

        {entries.length === 0 ? (
          <p className="px-2.5 py-4 text-[11px] text-dim" data-testid="watchlist-empty">
            No tickers watched. Add one below.
          </p>
        ) : null}
      </div>

      <form onSubmit={submit} className="flex-none border-t border-hair p-1.5">
        <div className="flex gap-1">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value.toUpperCase())}
            placeholder="ADD SYMBOL"
            aria-label="Add ticker to watchlist"
            data-testid="watchlist-add-input"
            className="num min-w-0 flex-1 border border-line bg-void px-2 py-1 text-[12px] uppercase placeholder:text-dim focus:border-primary focus:outline-none"
          />
          <button
            type="submit"
            data-testid="watchlist-add-submit"
            className="label border border-primary/60 px-2.5 text-[10px] text-primary transition-colors hover:bg-primary hover:text-void"
          >
            Add
          </button>
        </div>
        {error ? (
          <p className="mt-1 text-[10px] text-down" data-testid="watchlist-add-error">
            {error}
          </p>
        ) : null}
      </form>
    </Panel>
  );
}
