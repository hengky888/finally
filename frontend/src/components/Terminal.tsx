'use client';

import { useCallback, useMemo, useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Header } from './Header';
import { Heatmap } from './Heatmap';
import { MainChart } from './MainChart';
import { PnlChart } from './PnlChart';
import { PositionsTable } from './PositionsTable';
import { TradeBar } from './TradeBar';
import { Watchlist } from './Watchlist';
import { useChat } from '@/hooks/useChat';
import { usePortfolio } from '@/hooks/usePortfolio';
import { usePriceStream } from '@/hooks/usePriceStream';
import { addTicker, executeTrade, removeTicker } from '@/lib/api';
import { revaluePortfolio } from '@/lib/portfolio';
import type { TradeSide } from '@/lib/types';

/** Wires the live stream, the account state and the assistant into one screen. */
export function Terminal() {
  const stream = usePriceStream();
  const account = usePortfolio();
  const [picked, setPicked] = useState<string | null>(null);
  const [typedTicker, setTypedTicker] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);

  const chat = useChat(account.refresh);

  // Prices move far faster than the portfolio endpoint, so value everything
  // locally with the formulas the backend uses.
  const portfolio = useMemo(
    () => revaluePortfolio(account.portfolio, stream.tickers),
    [account.portfolio, stream.tickers],
  );

  // Until the user picks something, the terminal follows the top of the
  // watchlist, and the order ticket follows the selection.
  const selected = picked ?? account.watchlist[0]?.ticker ?? null;
  const tradeTicker = typedTicker ?? selected ?? '';

  const select = useCallback((ticker: string) => {
    setPicked(ticker);
    setTypedTicker(null);
  }, []);

  const held = portfolio.positions.find((p) => p.ticker === tradeTicker.toUpperCase());

  async function trade(side: TradeSide, ticker: string, quantity: number) {
    await executeTrade({ ticker, quantity, side });
    await account.refresh();
  }

  async function add(ticker: string) {
    await addTicker(ticker);
    await account.refresh();
  }

  async function remove(ticker: string) {
    await removeTicker(ticker);
    await account.refresh();
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-void">
      <Header
        totalValue={portfolio.total_value}
        cash={portfolio.cash_balance}
        unrealizedPnl={portfolio.total_unrealized_pnl}
        status={stream.status}
        seq={stream.seq}
        chatHidden={!chatOpen}
        onShowChat={() => setChatOpen(true)}
      />

      <main className="flex min-h-0 flex-1 gap-px overflow-hidden bg-void">
        <div className="hidden w-[236px] flex-none md:block">
          <Watchlist
            entries={account.watchlist}
            tickers={stream.tickers}
            series={stream.series}
            selected={selected}
            onSelect={select}
            onAdd={add}
            onRemove={remove}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-px">
          <MainChart
            ticker={selected}
            state={selected ? stream.tickers[selected] : undefined}
            points={selected ? (stream.series[selected] ?? []) : []}
          />

          <div className="flex h-[190px] flex-none gap-px">
            <Heatmap positions={portfolio.positions} selected={selected} onSelect={select} />
            <PnlChart history={account.history} />
          </div>

          <div className="flex h-[196px] flex-none">
            <PositionsTable
              positions={portfolio.positions}
              totalPnl={portfolio.total_unrealized_pnl}
              selected={selected}
              onSelect={select}
            />
          </div>
        </div>

        {chatOpen ? (
          <div className="w-[320px] flex-none lg:w-[352px]">
            <ChatPanel
              messages={chat.messages}
              pending={chat.pending}
              onSend={chat.send}
              onCollapse={() => setChatOpen(false)}
            />
          </div>
        ) : null}
      </main>

      <TradeBar
        tickers={stream.tickers}
        ticker={tradeTicker}
        onTickerChange={setTypedTicker}
        heldShares={held?.quantity ?? 0}
        cash={portfolio.cash_balance}
        onTrade={trade}
      />
    </div>
  );
}
