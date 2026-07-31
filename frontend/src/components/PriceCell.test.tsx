import { act, render, screen } from '@testing-library/react';
import { FLASH_MS, PriceCell } from './PriceCell';

const flash = () => screen.queryByTestId('px-flash');

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

describe('PriceCell', () => {
  it('renders the full price', () => {
    render(<PriceCell price={1234.5} direction="flat" moveSeq={0} testId="px" />);

    expect(screen.getByTestId('px')).toHaveTextContent('1,234.50');
  });

  it('does not flash before any move has happened', () => {
    render(<PriceCell price={190.2} direction="flat" moveSeq={0} testId="px" />);

    expect(flash()).not.toBeInTheDocument();
  });

  it('flashes up when the price genuinely rises', () => {
    const { rerender } = render(
      <PriceCell price={190.21} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={190.24} direction="up" moveSeq={1} testId="px" />);

    expect(flash()).toHaveClass('tick-up');
    expect(screen.getByTestId('px')).toHaveTextContent('190.24');
  });

  it('flashes down when the price genuinely falls', () => {
    const { rerender } = render(
      <PriceCell price={190.24} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={189.9} direction="down" moveSeq={1} testId="px" />);

    expect(flash()).toHaveClass('tick-down');
  });

  it('tints only the digits that changed', () => {
    const { rerender } = render(
      <PriceCell price={190.21} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={190.24} direction="up" moveSeq={1} testId="px" />);

    expect(flash()).toHaveTextContent('4');
    expect(screen.getByTestId('px')).toHaveTextContent('190.24');
  });

  it('does NOT flash on a flat tick', () => {
    const { rerender } = render(
      <PriceCell price={190.24} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={190.24} direction="flat" moveSeq={0} testId="px" />);
    rerender(<PriceCell price={190.24} direction="flat" moveSeq={0} testId="px" />);

    expect(flash()).not.toBeInTheDocument();
  });

  it('clears the flash and does not re-fire it on the flat ticks that follow a move', () => {
    const { rerender } = render(
      <PriceCell price={190.21} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={190.24} direction="up" moveSeq={1} testId="px" />);
    expect(flash()).toBeInTheDocument();

    act(() => void jest.advanceTimersByTime(FLASH_MS));
    expect(flash()).not.toBeInTheDocument();

    rerender(<PriceCell price={190.24} direction="flat" moveSeq={1} testId="px" />);
    act(() => void jest.advanceTimersByTime(FLASH_MS));

    expect(flash()).not.toBeInTheDocument();
    expect(screen.getByTestId('px')).toHaveTextContent('190.24');
  });

  it('flashes again on the next genuine move', () => {
    const { rerender } = render(
      <PriceCell price={190.21} direction="flat" moveSeq={0} testId="px" />,
    );

    rerender(<PriceCell price={190.24} direction="up" moveSeq={1} testId="px" />);
    act(() => void jest.advanceTimersByTime(FLASH_MS));
    rerender(<PriceCell price={190.11} direction="down" moveSeq={2} testId="px" />);

    expect(flash()).toHaveClass('tick-down');
  });
});
