'use client';

import { useState } from 'react';
import { money, quantity as formatQuantity } from '@/lib/format';
import type { TickerState, TradeSide } from '@/lib/types';

interface TradeBarProps {
  tickers: Record<string, TickerState>;
  ticker: string;
  onTickerChange: (ticker: string) => void;
  heldShares: number;
  cash: number;
  onTrade: (side: TradeSide, ticker: string, quantity: number) => Promise<void>;
}

type Status = { tone: 'ok' | 'error'; text: string } | null;

/** The command rail: market orders, instant fill, no confirmation step. */
export function TradeBar({
  tickers,
  ticker,
  onTickerChange,
  heldShares,
  cash,
  onTrade,
}: TradeBarProps) {
  const [qty, setQty] = useState('');
  const [status, setStatus] = useState<Status>(null);
  const [pending, setPending] = useState(false);

  const price = tickers[ticker.toUpperCase()]?.price ?? null;
  const parsedQty = Number.parseFloat(qty);
  const estimate = price !== null && parsedQty > 0 ? price * parsedQty : null;

  async function submit(side: TradeSide) {
    const symbol = ticker.trim().toUpperCase();
    if (!symbol || !(parsedQty > 0)) {
      setStatus({ tone: 'error', text: 'Enter a symbol and a quantity above zero.' });
      return;
    }
    setPending(true);
    setStatus(null);
    try {
      await onTrade(side, symbol, parsedQty);
      setStatus({ tone: 'ok', text: `Filled ${side} ${parsedQty} ${symbol}.` });
      setQty('');
    } catch (cause) {
      setStatus({
        tone: 'error',
        text: cause instanceof Error ? cause.message : 'Order rejected.',
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(event) => event.preventDefault()}
      data-testid="trade-bar"
      className="flex flex-wrap items-center gap-2 border-t border-line bg-raise/45 px-3 py-2"
    >
      <span className="label text-[10px] text-accent">Order</span>

      <input
        value={ticker}
        onChange={(event) => onTickerChange(event.target.value.toUpperCase())}
        placeholder="SYMBOL"
        aria-label="Ticker"
        data-testid="trade-ticker-input"
        className="num w-24 border border-line bg-void px-2 py-1 text-[13px] uppercase placeholder:text-dim focus:border-primary focus:outline-none"
      />

      <input
        value={qty}
        onChange={(event) => setQty(event.target.value)}
        inputMode="decimal"
        placeholder="QTY"
        aria-label="Quantity"
        data-testid="trade-quantity-input"
        className="num w-24 border border-line bg-void px-2 py-1 text-[13px] placeholder:text-dim focus:border-primary focus:outline-none"
      />

      <button
        type="button"
        disabled={pending}
        onClick={() => submit('buy')}
        data-testid="trade-buy-button"
        className="label bg-up px-5 py-1.5 text-[11px] text-void transition-opacity hover:opacity-85 disabled:opacity-40"
      >
        Buy
      </button>
      <button
        type="button"
        disabled={pending}
        onClick={() => submit('sell')}
        data-testid="trade-sell-button"
        className="label bg-down px-5 py-1.5 text-[11px] text-void transition-opacity hover:opacity-85 disabled:opacity-40"
      >
        Sell
      </button>

      <dl className="flex items-baseline gap-4 border-l border-line pl-4 text-[10px]">
        <Readout term="Last" value={price === null ? '--' : money(price)} />
        <Readout term="Est" value={estimate === null ? '--' : money(estimate)} testId="trade-estimate" />
        <Readout term="Held" value={formatQuantity(heldShares)} testId="trade-held" />
        <Readout term="Cash" value={money(cash)} />
      </dl>

      <p
        data-testid="trade-status"
        data-tone={status?.tone ?? 'idle'}
        className={`ml-auto text-[11px] ${status?.tone === 'error' ? 'text-down' : 'text-up'}`}
      >
        {status?.text ?? ''}
      </p>
    </form>
  );
}

function Readout({ term, value, testId }: { term: string; value: string; testId?: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="label text-dim">{term}</dt>
      <dd className="num text-ink" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}
