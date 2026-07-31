import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Header } from './Header';

function setup(overrides: Partial<Parameters<typeof Header>[0]> = {}) {
  const props = {
    totalValue: 12_483.2,
    cash: 3204.11,
    unrealizedPnl: 279.09,
    status: 'live' as const,
    seq: 42,
    chatHidden: false,
    onShowChat: jest.fn(),
    ...overrides,
  };
  render(<Header {...props} />);
  return props;
}

describe('Header', () => {
  it('shows total value and cash balance', () => {
    setup();

    expect(screen.getByTestId('total-value')).toHaveTextContent('12,483.20');
    expect(screen.getByTestId('cash-balance')).toHaveTextContent('3,204.11');
  });

  it('signs and colours unrealized P&L', () => {
    setup({ unrealizedPnl: -50 });

    expect(screen.getByTestId('header-unrealized')).toHaveTextContent('-50.00');
    expect(screen.getByTestId('header-unrealized')).toHaveClass('text-down');
  });

  it.each([
    ['live', 'Live'],
    ['connecting', 'Reconnecting'],
    ['down', 'Disconnected'],
  ] as const)('reports the %s connection state', (status, text) => {
    setup({ status });

    const indicator = screen.getByTestId('connection-status');
    expect(indicator).toHaveAttribute('data-status', status);
    expect(indicator).toHaveTextContent(text);
  });

  it('counts ticks so a stalled stream is visible', () => {
    setup({ seq: 1024 });

    expect(screen.getByTestId('stream-seq')).toHaveTextContent('TICK 1024');
  });

  it('offers to reopen the assistant only when it is hidden', async () => {
    const props = setup({ chatHidden: true });

    await userEvent.click(screen.getByTestId('chat-show'));

    expect(props.onShowChat).toHaveBeenCalled();
  });

  it('hides the assistant button while the panel is open', () => {
    setup({ chatHidden: false });

    expect(screen.queryByTestId('chat-show')).not.toBeInTheDocument();
  });
});
