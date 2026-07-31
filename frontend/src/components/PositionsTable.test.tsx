import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PositionsTable } from './PositionsTable';
import { position } from '@/test/factories';

const positions = [
  position({ ticker: 'AAPL', quantity: 10, avg_cost: 180, current_price: 190 }),
  position({ ticker: 'TSLA', quantity: 4, avg_cost: 260, current_price: 234 }),
];

function setup(overrides: Partial<Parameters<typeof PositionsTable>[0]> = {}) {
  const props = {
    positions,
    totalPnl: 100 - 104,
    selected: 'AAPL',
    onSelect: jest.fn(),
    ...overrides,
  };
  render(<PositionsTable {...props} />);
  return props;
}

describe('PositionsTable', () => {
  it('renders a row per position', () => {
    setup();

    expect(screen.getByTestId('positions-row-AAPL')).toBeInTheDocument();
    expect(screen.getByTestId('positions-row-TSLA')).toBeInTheDocument();
  });

  it('shows quantity, average cost and the current price', () => {
    setup();

    expect(screen.getByTestId('position-qty-AAPL')).toHaveTextContent('10');
    expect(screen.getByTestId('position-avg-cost-AAPL')).toHaveTextContent('180.00');
    expect(screen.getByTestId('position-price-AAPL')).toHaveTextContent('190.00');
  });

  it('computes unrealized P&L and percent change for a winner', () => {
    setup();

    expect(screen.getByTestId('position-pnl-AAPL')).toHaveTextContent('+100.00');
    expect(screen.getByTestId('position-pnl-pct-AAPL')).toHaveTextContent('+5.56%');
  });

  it('computes unrealized P&L and percent change for a loser', () => {
    setup();

    expect(screen.getByTestId('position-pnl-TSLA')).toHaveTextContent('-104.00');
    expect(screen.getByTestId('position-pnl-pct-TSLA')).toHaveTextContent('-10.00%');
  });

  it('colours gains and losses differently', () => {
    setup();

    expect(screen.getByTestId('position-pnl-AAPL')).toHaveClass('text-up');
    expect(screen.getByTestId('position-pnl-TSLA')).toHaveClass('text-down');
  });

  it('totals unrealized P&L in the panel header', () => {
    setup();

    expect(screen.getByTestId('positions-total-pnl')).toHaveTextContent('-4.00');
  });

  it('selects a ticker when its row is clicked', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('positions-row-TSLA'));

    expect(props.onSelect).toHaveBeenCalledWith('TSLA');
  });

  it('explains how to open a position when there are none', () => {
    setup({ positions: [], totalPnl: 0 });

    expect(screen.getByTestId('positions-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('positions-row-AAPL')).not.toBeInTheDocument();
  });
});
