'use client';

import { money, signedMoney } from '@/lib/format';
import type { ConnectionStatus } from '@/lib/types';

interface HeaderProps {
  totalValue: number;
  cash: number;
  unrealizedPnl: number;
  status: ConnectionStatus;
  seq: number;
  chatHidden: boolean;
  onShowChat: () => void;
}

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  live: 'Live',
  connecting: 'Reconnecting',
  down: 'Disconnected',
};

const STATUS_COLOR: Record<ConnectionStatus, string> = {
  live: 'bg-up',
  connecting: 'bg-accent',
  down: 'bg-down',
};

export function Header({
  totalValue,
  cash,
  unrealizedPnl,
  status,
  seq,
  chatHidden,
  onShowChat,
}: HeaderProps) {
  return (
    <header className="flex flex-none items-stretch border-b border-line bg-panel">
      <div className="flex items-baseline gap-2 border-r border-hair px-3.5 py-2">
        <span className="label text-[15px] tracking-[0.18em] text-accent">FinAlly</span>
        <span className="label hidden text-[9px] text-dim sm:inline">Trading workstation</span>
      </div>

      <Metric label="Total value" testId="total-value" value={money(totalValue)} accent="text-ink" />
      <Metric label="Cash" testId="cash-balance" value={money(cash)} accent="text-ink" />
      <Metric
        label="Unrealized"
        testId="header-unrealized"
        value={signedMoney(unrealizedPnl)}
        accent={unrealizedPnl >= 0 ? 'text-up' : 'text-down'}
      />

      <div className="ml-auto flex items-center gap-3 px-3.5">
        {chatHidden ? (
          <button
            type="button"
            onClick={onShowChat}
            data-testid="chat-show"
            className="label border border-violet px-2 py-1 text-[10px] text-violet-lit hover:bg-violet hover:text-white"
          >
            Assistant
          </button>
        ) : null}

        <span className="num hidden text-[10px] text-dim md:inline" data-testid="stream-seq">
          TICK {seq}
        </span>

        <span
          className="flex items-center gap-1.5"
          data-testid="connection-status"
          data-status={status}
          title={STATUS_TEXT[status]}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${STATUS_COLOR[status]} ${
              status === 'live' ? '' : 'pulse'
            }`}
          />
          <span className="label text-[10px] text-muted">{STATUS_TEXT[status]}</span>
        </span>
      </div>
    </header>
  );
}

function Metric({
  label,
  value,
  testId,
  accent,
}: {
  label: string;
  value: string;
  testId: string;
  accent: string;
}) {
  return (
    <div className="flex flex-col justify-center border-r border-hair px-3.5 py-1">
      <span className="label text-[9px] text-dim">{label}</span>
      <span className={`num text-[15px] leading-tight ${accent}`} data-testid={testId}>
        {value}
      </span>
    </div>
  );
}
