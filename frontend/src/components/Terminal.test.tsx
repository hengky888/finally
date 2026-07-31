import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Terminal } from './Terminal';
import { MockEventSource } from '@/test/mockEventSource';
import { envelope, portfolio, position, tick } from '@/test/factories';

const ACCOUNT = portfolio({
  cash_balance: 8100,
  positions: [position({ ticker: 'AAPL', quantity: 10, avg_cost: 180, current_price: 190 })],
});

const HISTORY = [
  { total_value: 10_000, recorded_at: '2026-07-31T10:00:00' },
  { total_value: 10_020, recorded_at: '2026-07-31T10:00:30' },
];

const WATCHLIST = [
  { ticker: 'AAPL', price: 190 },
  { ticker: 'TSLA', price: 250 },
];

function stubApi() {
  const posted: { url: string; body: unknown }[] = [];
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method) posted.push({ url, body: JSON.parse(String(init.body ?? 'null')) });
    const body = url.includes('/api/portfolio/history')
      ? HISTORY
      : url.includes('/api/portfolio')
        ? ACCOUNT
        : url.includes('/api/watchlist')
          ? WATCHLIST
          : { message: 'ok' };
    return { ok: true, status: 200, json: async () => body };
  }) as unknown as typeof fetch;
  return posted;
}

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

beforeEach(() => {
  MockEventSource.install();
  stubApi();
});

async function mount() {
  render(<Terminal />);
  await screen.findByTestId('watchlist-row-AAPL');
}

describe('Terminal', () => {
  it('renders every panel of the workstation', async () => {
    await mount();

    for (const testId of [
      'total-value',
      'cash-balance',
      'connection-status',
      'watchlist',
      'main-chart',
      'heatmap',
      'pnl-chart',
      'positions-table',
      'trade-bar',
      'chat-panel',
    ]) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
  });

  it('shows the served cash balance and total value', async () => {
    await mount();

    expect(screen.getByTestId('cash-balance')).toHaveTextContent('8,100.00');
    expect(screen.getByTestId('total-value')).toHaveTextContent('10,000.00');
  });

  it('revalues the portfolio live as prices tick in', async () => {
    await mount();

    act(() => MockEventSource.latest().emit(envelope(1, [tick('AAPL', 200), tick('TSLA', 250)])));

    await waitFor(() =>
      // 8100 cash + 10 shares at 200
      expect(screen.getByTestId('total-value')).toHaveTextContent('10,100.00'),
    );
    expect(screen.getByTestId('position-price-AAPL')).toHaveTextContent('200.00');
    expect(screen.getByTestId('position-pnl-AAPL')).toHaveTextContent('+200.00');
  });

  it('selects the first watched ticker for the main chart', async () => {
    await mount();

    expect(screen.getByTestId('main-chart-ticker')).toHaveTextContent('AAPL');
  });

  it('moves the main chart and the order ticket to a clicked ticker', async () => {
    await mount();

    await userEvent.click(screen.getByTestId('watchlist-row-TSLA'));

    expect(screen.getByTestId('main-chart-ticker')).toHaveTextContent('TSLA');
    expect(screen.getByTestId('trade-ticker-input')).toHaveValue('TSLA');
  });

  it('starts the price charts empty and fills them from the stream', async () => {
    await mount();
    expect(screen.getByTestId('main-chart-plot-empty')).toBeInTheDocument();

    act(() => MockEventSource.latest().emit(envelope(1, [tick('AAPL', 190)])));
    act(() => MockEventSource.latest().emit(envelope(2, [tick('AAPL', 191, 'up', 190)])));

    await waitFor(() => expect(screen.getByTestId('main-chart-plot')).toBeInTheDocument());
  });

  it('plots the P&L chart from snapshots that survived reload', async () => {
    await mount();

    expect(screen.getByTestId('pnl-chart-plot')).toHaveAttribute('data-points', '2');
  });

  it('posts a trade and refreshes the account', async () => {
    const posted = stubApi();
    await mount();

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '3');
    await userEvent.click(screen.getByTestId('trade-buy-button'));

    await waitFor(() =>
      expect(posted).toContainEqual({
        url: '/api/portfolio/trade',
        body: { ticker: 'AAPL', quantity: 3, side: 'buy' },
      }),
    );
  });

  it('posts a watchlist addition', async () => {
    const posted = stubApi();
    await mount();

    await userEvent.type(screen.getByTestId('watchlist-add-input'), 'pypl');
    await userEvent.click(screen.getByTestId('watchlist-add-submit'));

    await waitFor(() =>
      expect(posted).toContainEqual({ url: '/api/watchlist', body: { ticker: 'PYPL' } }),
    );
  });

  it('posts a watchlist removal', async () => {
    const posted = stubApi();
    await mount();

    await userEvent.click(screen.getByTestId('watchlist-remove-TSLA'));

    await waitFor(() =>
      expect(posted).toContainEqual({ url: '/api/watchlist/TSLA', body: null }),
    );
  });

  it('sends a chat message and renders the reply with its actions', async () => {
    global.fetch = jest.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.includes('/api/chat')
          ? {
              message: 'Bought 2 AAPL for you.',
              actions: { trades: [{ ticker: 'AAPL', side: 'buy', quantity: 2, price: 190 }] },
            }
          : url.includes('/api/portfolio/history')
            ? HISTORY
            : url.includes('/api/portfolio')
              ? ACCOUNT
              : WATCHLIST,
    })) as unknown as typeof fetch;
    await mount();

    await userEvent.type(screen.getByTestId('chat-input'), 'buy 2 AAPL');
    await userEvent.click(screen.getByTestId('chat-send'));

    expect(await screen.findByTestId('chat-message-1')).toHaveTextContent('Bought 2 AAPL for you.');
    expect(screen.getByTestId('chat-actions-1')).toHaveTextContent('BUY 2 AAPL @ 190.00');
  });

  it('hides and restores the assistant panel', async () => {
    await mount();

    await userEvent.click(screen.getByTestId('chat-collapse'));
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId('chat-show'));
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
  });

  it('reports a disconnected stream in the header', async () => {
    await mount();

    act(() => MockEventSource.latest().fail(MockEventSource.CLOSED));

    expect(screen.getByTestId('connection-status')).toHaveAttribute('data-status', 'down');
  });
});
