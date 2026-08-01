/**
 * Reduction of the SSE price stream into terminal state.
 *
 * The stream re-emits every priced ticker on every tick, so most payloads are
 * `direction: "flat"`. `moveSeq` advances only on a genuine move — it is the
 * single signal the UI flashes on, which keeps a quiet market visually still.
 */

import type { PriceEnvelope, SeriesPoint, TickerState } from './types';

export const SERIES_CAP = 900;

export interface StreamState {
  tickers: Record<string, TickerState>;
  series: Record<string, SeriesPoint[]>;
  seq: number;
  lastTickAt: number;
}

export const emptyStream: StreamState = { tickers: {}, series: {}, seq: 0, lastTickAt: 0 };

export function applyEnvelope(
  state: StreamState,
  envelope: PriceEnvelope,
  cap = SERIES_CAP,
): StreamState {
  const tickers: Record<string, TickerState> = {};
  const series: Record<string, SeriesPoint[]> = {};

  for (const [ticker, tick] of Object.entries(envelope.prices)) {
    const previous = state.tickers[ticker];
    const moved = tick.direction !== 'flat';

    tickers[ticker] = {
      ticker,
      price: tick.price,
      direction: tick.direction,
      moveSeq: (previous?.moveSeq ?? 0) + (moved ? 1 : 0),
      anchor: previous?.anchor ?? tick.price,
    };

    const history = state.series[ticker] ?? [];
    const point = { t: tick.timestamp * 1000, p: tick.price };
    series[ticker] = history.length >= cap ? [...history.slice(1), point] : [...history, point];
  }

  return { tickers, series, seq: envelope.seq, lastTickAt: envelope.ts * 1000 };
}

/** Parse one SSE `data:` payload; ignores anything that is not a price envelope. */
export function parseEnvelope(data: string): PriceEnvelope | null {
  const parsed: unknown = JSON.parse(data);
  if (parsed && typeof parsed === 'object' && 'prices' in parsed) {
    return parsed as PriceEnvelope;
  }
  return null;
}
