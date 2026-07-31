import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Heatmap } from './Heatmap';
import { position } from '@/test/factories';

const positions = [
  position({ ticker: 'AAPL', quantity: 10, avg_cost: 180, current_price: 190 }),
  position({ ticker: 'TSLA', quantity: 2, avg_cost: 260, current_price: 234 }),
];

function setup(overrides: Partial<Parameters<typeof Heatmap>[0]> = {}) {
  const props = { positions, selected: null, onSelect: jest.fn(), ...overrides };
  render(<Heatmap {...props} />);
  return props;
}

describe('Heatmap', () => {
  it('renders a tile per position', () => {
    setup();

    expect(screen.getByTestId('heatmap-tile-AAPL')).toBeInTheDocument();
    expect(screen.getByTestId('heatmap-tile-TSLA')).toBeInTheDocument();
  });

  it('marks tiles as gain or loss', () => {
    setup();

    expect(screen.getByTestId('heatmap-tile-AAPL')).toHaveAttribute('data-pnl', 'gain');
    expect(screen.getByTestId('heatmap-tile-TSLA')).toHaveAttribute('data-pnl', 'loss');
  });

  it('sizes tiles by portfolio weight', () => {
    setup();

    const big = screen.getByTestId('heatmap-tile-AAPL').style;
    const small = screen.getByTestId('heatmap-tile-TSLA').style;

    expect(Number.parseFloat(big.width) * Number.parseFloat(big.height)).toBeGreaterThan(
      Number.parseFloat(small.width) * Number.parseFloat(small.height),
    );
  });

  it('selects a ticker when a tile is clicked', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('heatmap-tile-TSLA'));

    expect(props.onSelect).toHaveBeenCalledWith('TSLA');
  });

  it('shows an empty state with no positions', () => {
    setup({ positions: [] });

    expect(screen.getByTestId('heatmap-empty')).toBeInTheDocument();
  });
});
