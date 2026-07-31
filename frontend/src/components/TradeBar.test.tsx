import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TradeBar } from './TradeBar';
import { tickerState } from '@/test/factories';

function setup(overrides: Partial<Parameters<typeof TradeBar>[0]> = {}) {
  const props = {
    tickers: { AAPL: tickerState({ ticker: 'AAPL', price: 190 }) },
    ticker: 'AAPL',
    onTickerChange: jest.fn(),
    heldShares: 12,
    cash: 5000,
    onTrade: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<TradeBar {...props} />);
  return props;
}

describe('TradeBar', () => {
  it('shows the live price, shares held and cash', () => {
    setup();

    expect(screen.getByTestId('trade-held')).toHaveTextContent('12');
    expect(screen.getByTestId('trade-bar')).toHaveTextContent('5,000.00');
  });

  it('estimates the order cost from the live price', async () => {
    setup();

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '3');

    expect(screen.getByTestId('trade-estimate')).toHaveTextContent('570.00');
  });

  it('buys the entered quantity', async () => {
    const props = setup();

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '5');
    await userEvent.click(screen.getByTestId('trade-buy-button'));

    expect(props.onTrade).toHaveBeenCalledWith('buy', 'AAPL', 5);
    expect(await screen.findByTestId('trade-status')).toHaveTextContent('Filled buy 5 AAPL.');
  });

  it('sells the entered quantity', async () => {
    const props = setup();

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '2');
    await userEvent.click(screen.getByTestId('trade-sell-button'));

    expect(props.onTrade).toHaveBeenCalledWith('sell', 'AAPL', 2);
  });

  it('clears the quantity after a fill', async () => {
    setup();
    const qty = screen.getByTestId('trade-quantity-input');

    await userEvent.type(qty, '5');
    await userEvent.click(screen.getByTestId('trade-buy-button'));

    expect(await screen.findByTestId('trade-status')).toHaveTextContent('Filled');
    expect(qty).toHaveValue('');
  });

  it('uppercases a typed symbol', async () => {
    const props = setup({ ticker: '' });

    await userEvent.type(screen.getByTestId('trade-ticker-input'), 'p');

    expect(props.onTickerChange).toHaveBeenCalledWith('P');
  });

  it('rejects a missing quantity before calling the backend', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('trade-buy-button'));

    expect(props.onTrade).not.toHaveBeenCalled();
    expect(screen.getByTestId('trade-status')).toHaveAttribute('data-tone', 'error');
  });

  it('rejects a zero quantity', async () => {
    const props = setup();

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '0');
    await userEvent.click(screen.getByTestId('trade-buy-button'));

    expect(props.onTrade).not.toHaveBeenCalled();
  });

  it('surfaces the backend rejection message', async () => {
    setup({ onTrade: jest.fn().mockRejectedValue(new Error('Insufficient cash')) });

    await userEvent.type(screen.getByTestId('trade-quantity-input'), '900');
    await userEvent.click(screen.getByTestId('trade-buy-button'));

    const status = await screen.findByTestId('trade-status');
    expect(status).toHaveTextContent('Insufficient cash');
    expect(status).toHaveAttribute('data-tone', 'error');
  });

  it('shows no estimate for an unpriced symbol', () => {
    setup({ ticker: 'PYPL', tickers: {} });

    expect(screen.getByTestId('trade-estimate')).toHaveTextContent('--');
  });
});
