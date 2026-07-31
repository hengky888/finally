'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { money, quantity } from '@/lib/format';
import type { ChatActions, ChatMessage } from '@/lib/types';

interface ChatPanelProps {
  messages: ChatMessage[];
  pending: boolean;
  onSend: (message: string) => Promise<void>;
  onCollapse: () => void;
}

export function ChatPanel({ messages, pending, onSend, onCollapse }: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, pending]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setDraft('');
    await onSend(text);
  }

  return (
    <aside
      className="panel h-full w-full bg-raise/50"
      data-testid="chat-panel"
      aria-label="AI assistant"
    >
      <header className="panel-head">
        <h2 className="label text-[10px] text-violet-lit">FinAlly assistant</h2>
        <button
          type="button"
          onClick={onCollapse}
          data-testid="chat-collapse"
          aria-label="Collapse assistant"
          className="label text-[10px] text-dim hover:text-ink"
        >
          Hide
        </button>
      </header>

      <div className="flex-1 space-y-2.5 overflow-y-auto p-2.5" data-testid="chat-messages">
        {messages.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-dim" data-testid="chat-empty">
            Ask about your positions, request analysis, or tell the assistant to trade. It
            executes orders and watchlist changes directly.
          </p>
        ) : null}

        {messages.map((message, index) => (
          <article
            key={index}
            data-testid={`chat-message-${index}`}
            data-role={message.role}
            className={
              message.role === 'user'
                ? 'border-l-2 border-violet bg-void/50 px-2.5 py-1.5'
                : 'border-l-2 border-primary/50 px-2.5 py-1.5'
            }
          >
            <p className="label mb-1 text-[9px] text-dim">
              {message.role === 'user' ? 'You' : 'FinAlly'}
            </p>
            <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-ink">
              {message.content}
            </p>
            {message.actions ? (
              <ActionLog actions={message.actions} testId={`chat-actions-${index}`} />
            ) : null}
          </article>
        ))}

        {pending ? (
          <p
            className="label flex items-center gap-2 px-2.5 text-[10px] text-dim"
            data-testid="chat-loading"
          >
            <span className="pulse inline-block h-1.5 w-1.5 rounded-full bg-violet" />
            Thinking
          </p>
        ) : null}

        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="flex-none border-t border-hair p-2">
        <div className="flex gap-1.5">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask or instruct"
            aria-label="Message the assistant"
            data-testid="chat-input"
            className="min-w-0 flex-1 border border-line bg-void px-2 py-1.5 text-[12px] placeholder:text-dim focus:border-violet focus:outline-none"
          />
          <button
            type="submit"
            disabled={pending}
            data-testid="chat-send"
            className="label bg-violet px-3.5 text-[10px] text-white transition-opacity hover:opacity-85 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </aside>
  );
}

/** Inline confirmation of what the assistant actually executed. */
function ActionLog({ actions, testId }: { actions: ChatActions; testId: string }) {
  const trades = actions.trades ?? [];
  const changes = actions.watchlist_changes ?? [];
  const errors = actions.errors ?? [];
  if (!trades.length && !changes.length && !errors.length) return null;

  return (
    <ul className="mt-1.5 space-y-0.5 border-t border-hair pt-1.5" data-testid={testId}>
      {trades.map((trade, i) => (
        <li key={`t${i}`} className="num text-[10px]">
          <span className={trade.side === 'buy' ? 'text-up' : 'text-down'}>
            {trade.side.toUpperCase()}
          </span>{' '}
          {quantity(trade.quantity)} {trade.ticker} @ {money(trade.price)}
        </li>
      ))}
      {changes.map((change, i) => (
        <li key={`w${i}`} className="num text-[10px] text-primary">
          WATCH {change.action === 'add' ? '+' : '-'}
          {change.ticker}
        </li>
      ))}
      {errors.map((error, i) => (
        <li key={`e${i}`} className="text-[10px] text-down">
          {error}
        </li>
      ))}
    </ul>
  );
}
