/** Wire types for the FinAlly backend (PLAN.md section 8). */

export type Direction = 'up' | 'down' | 'flat';

/** One ticker's entry inside an SSE tick. */
export interface PriceTick {
  ticker: string;
  price: number;
  previous_price: number;
  change: number;
  change_percent: number;
  direction: Direction;
  timestamp: number;
}

/** The envelope pushed by `/api/stream/prices` — every priced ticker, every tick. */
export interface PriceEnvelope {
  seq: number;
  ts: number;
  prices: Record<string, PriceTick>;
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  position_value: number;
  unrealized_pnl: number;
  /** Ratio, not percent: (current_price - avg_cost) / avg_cost. */
  pnl_pct: number;
}

export interface Portfolio {
  cash_balance: number;
  positions: Position[];
  total_value: number;
  total_unrealized_pnl: number;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface WatchlistEntry {
  ticker: string;
  price: number | null;
}

export type TradeSide = 'buy' | 'sell';

export interface TradeRequest {
  ticker: string;
  quantity: number;
  side: TradeSide;
}

export interface ExecutedTrade {
  ticker: string;
  side: TradeSide;
  quantity: number;
  price: number;
}

export interface WatchlistChange {
  ticker: string;
  action: 'add' | 'remove';
}

/** What the assistant actually did, echoed back for inline confirmation. */
export interface ChatActions {
  trades?: ExecutedTrade[];
  watchlist_changes?: WatchlistChange[];
  errors?: string[];
}

export interface ChatResponse {
  message: string;
  actions?: ChatActions;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  actions?: ChatActions;
}

/** Live price plus the per-session state the terminal derives from the stream. */
export interface TickerState {
  ticker: string;
  price: number;
  direction: Direction;
  /** Increments only on a genuine move, so flashes never fire on flat ticks. */
  moveSeq: number;
  /** First price seen this session — the anchor for session change %. */
  anchor: number;
}

export interface SeriesPoint {
  t: number;
  p: number;
}

export type ConnectionStatus = 'connecting' | 'live' | 'down';
