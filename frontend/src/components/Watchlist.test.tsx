import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Watchlist } from './Watchlist';
import { tickerState } from '@/test/factories';

const entries = [{ ticker: 'AAPL', price: 190 }, { ticker: 'TSLA', price: 250 }];

const tickers = {
  AAPL: tickerState({ ticker: 'AAPL', price: 199.5, anchor: 190, direction: 'up', moveSeq: 3 }),
  TSLA: tickerState({ ticker: 'TSLA', price: 240, anchor: 250, direction: 'down', moveSeq: 2 }),
};

function setup(overrides: Partial<Parameters<typeof Watchlist>[0]> = {}) {
  const props = {
    entries,
    tickers,
    series: { AAPL: [{ t: 1, p: 190 }, { t: 2, p: 199.5 }], TSLA: [] },
    selected: 'AAPL',
    onSelect: jest.fn(),
    onAdd: jest.fn().mockResolvedValue(undefined),
    onRemove: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<Watchlist {...props} />);
  return props;
}

describe('Watchlist', () => {
  it('renders a row per watched ticker with its live price', () => {
    setup();

    expect(screen.getByTestId('watchlist-ticker-AAPL')).toHaveTextContent('AAPL');
    expect(screen.getByTestId('watchlist-price-AAPL')).toHaveTextContent('199.50');
    expect(screen.getByTestId('watchlist-price-TSLA')).toHaveTextContent('240.00');
  });

  it('shows the session change against the first price seen', () => {
    setup();

    expect(screen.getByTestId('watchlist-change-AAPL')).toHaveTextContent('+5.00%');
    expect(screen.getByTestId('watchlist-change-TSLA')).toHaveTextContent('-4.00%');
  });

  it('marks a ticker with no quote yet as unpriced', () => {
    setup({ entries: [{ ticker: 'PYPL', price: null }], tickers: {} });

    expect(screen.getByTestId('watchlist-price-PYPL')).toHaveTextContent('—');
  });

  it('draws a sparkline once points have accumulated', () => {
    setup();

    expect(screen.getByTestId('watchlist-sparkline-AAPL')).toHaveAttribute('data-points', '2');
    expect(screen.getByTestId('watchlist-sparkline-TSLA')).toHaveAttribute('data-points', '0');
  });

  it('marks the selected row', () => {
    setup();

    expect(screen.getByTestId('watchlist-row-AAPL')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('watchlist-row-TSLA')).toHaveAttribute('data-selected', 'false');
  });

  it('selects a ticker when its row is clicked', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('watchlist-row-TSLA'));

    expect(props.onSelect).toHaveBeenCalledWith('TSLA');
  });

  it('adds an uppercased ticker and clears the field', async () => {
    const props = setup();
    const input = screen.getByTestId('watchlist-add-input');

    await userEvent.type(input, 'pypl');
    await userEvent.click(screen.getByTestId('watchlist-add-submit'));

    expect(props.onAdd).toHaveBeenCalledWith('PYPL');
    await waitFor(() => expect(input).toHaveValue(''));
  });

  it('ignores an empty add', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('watchlist-add-submit'));

    expect(props.onAdd).not.toHaveBeenCalled();
  });

  it('reports a rejected ticker', async () => {
    const props = setup({ onAdd: jest.fn().mockRejectedValue(new Error('Unknown symbol ZZZZ')) });

    await userEvent.type(screen.getByTestId('watchlist-add-input'), 'ZZZZ');
    await userEvent.click(screen.getByTestId('watchlist-add-submit'));

    expect(props.onAdd).toHaveBeenCalledWith('ZZZZ');
    expect(await screen.findByTestId('watchlist-add-error')).toHaveTextContent('Unknown symbol ZZZZ');
  });

  it('removes a ticker without selecting it', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('watchlist-remove-TSLA'));

    expect(props.onRemove).toHaveBeenCalledWith('TSLA');
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it('invites the user to add one when the list is empty', () => {
    setup({ entries: [] });

    expect(screen.getByTestId('watchlist-empty')).toBeInTheDocument();
  });
});
