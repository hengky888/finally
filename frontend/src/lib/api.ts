/**
 * Backend client. In the container the app is served from the same origin as
 * the API, so paths stay relative; `NEXT_PUBLIC_API_BASE` points a dev server at
 * a backend on another port.
 */

import type {
  ChatResponse,
  Portfolio,
  Snapshot,
  TradeRequest,
  WatchlistEntry,
} from './types';

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? '';

export function apiUrl(path: string): string {
  return `${BASE}${path}`;
}

/** Surfaces the backend's rejection text (TradeError) instead of a status code. */
export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(detail(body) ?? `Request failed (${response.status})`);
  }
  return body as T;
}

function detail(body: unknown): string | null {
  if (body && typeof body === 'object' && 'detail' in body) {
    const value = (body as { detail: unknown }).detail;
    if (typeof value === 'string') return value;
  }
  return null;
}

export function getPortfolio(): Promise<Portfolio> {
  return request<Portfolio>('/api/portfolio');
}

export function getHistory(): Promise<Snapshot[]> {
  return request<Snapshot[] | { snapshots: Snapshot[] }>('/api/portfolio/history').then(
    (body) => (Array.isArray(body) ? body : body.snapshots),
  );
}

export function executeTrade(trade: TradeRequest): Promise<unknown> {
  return request('/api/portfolio/trade', { method: 'POST', body: JSON.stringify(trade) });
}

export function getWatchlist(): Promise<WatchlistEntry[]> {
  return request<unknown>('/api/watchlist').then(normalizeWatchlist);
}

export function addTicker(ticker: string): Promise<unknown> {
  return request('/api/watchlist', { method: 'POST', body: JSON.stringify({ ticker }) });
}

export function removeTicker(ticker: string): Promise<unknown> {
  return request(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
}

export function sendChat(message: string): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

/**
 * PLAN.md pins the watchlist path but not its envelope, so accept the plausible
 * shapes: a bare array, `{watchlist: []}` or `{tickers: []}`, of strings or rows.
 */
export function normalizeWatchlist(body: unknown): WatchlistEntry[] {
  const rows = Array.isArray(body)
    ? body
    : ((body as { watchlist?: unknown[]; tickers?: unknown[] })?.watchlist ??
      (body as { tickers?: unknown[] })?.tickers ??
      []);

  return rows.map((row) =>
    typeof row === 'string'
      ? { ticker: row, price: null }
      : {
          ticker: String((row as WatchlistEntry).ticker),
          price: (row as WatchlistEntry).price ?? null,
        },
  );
}
