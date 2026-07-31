import { act, renderHook } from '@testing-library/react';
import { usePriceStream } from './usePriceStream';
import { MockEventSource } from '@/test/mockEventSource';
import { envelope, tick } from '@/test/factories';

beforeEach(() => MockEventSource.install());

describe('usePriceStream', () => {
  it('subscribes to the price stream', () => {
    renderHook(() => usePriceStream());

    expect(MockEventSource.latest().url).toBe('/api/stream/prices');
  });

  it('starts out connecting and goes live when the stream opens', () => {
    const { result } = renderHook(() => usePriceStream());
    expect(result.current.status).toBe('connecting');

    act(() => MockEventSource.latest().open());

    expect(result.current.status).toBe('live');
  });

  it('applies incoming ticks to the ticker map', () => {
    const { result } = renderHook(() => usePriceStream());

    act(() => {
      MockEventSource.latest().open();
      MockEventSource.latest().emit(envelope(1, [tick('AAPL', 190), tick('TSLA', 250)]));
    });

    expect(result.current.tickers.AAPL.price).toBe(190);
    expect(result.current.tickers.TSLA.price).toBe(250);
    expect(result.current.seq).toBe(1);
  });

  it('counts a move only when a tick is not flat', () => {
    const { result } = renderHook(() => usePriceStream());
    const source = MockEventSource.latest();

    act(() => source.emit(envelope(1, [tick('AAPL', 190)])));
    act(() => source.emit(envelope(2, [tick('AAPL', 190, 'flat', 190)])));
    expect(result.current.tickers.AAPL.moveSeq).toBe(0);

    act(() => source.emit(envelope(3, [tick('AAPL', 191, 'up', 190)])));
    expect(result.current.tickers.AAPL.moveSeq).toBe(1);
  });

  it('accumulates a per-ticker series across ticks', () => {
    const { result } = renderHook(() => usePriceStream());
    const source = MockEventSource.latest();

    act(() => source.emit(envelope(1, [tick('AAPL', 190)])));
    act(() => source.emit(envelope(2, [tick('AAPL', 191, 'up', 190)])));

    expect(result.current.series.AAPL).toHaveLength(2);
  });

  it('ignores payloads that carry no prices', () => {
    const { result } = renderHook(() => usePriceStream());

    act(() => MockEventSource.latest().emit({ hello: 'world' }));

    expect(result.current.tickers).toEqual({});
  });

  it('reports reconnecting while EventSource retries', () => {
    const { result } = renderHook(() => usePriceStream());

    act(() => MockEventSource.latest().open());
    act(() => MockEventSource.latest().fail(MockEventSource.CONNECTING));

    expect(result.current.status).toBe('connecting');
  });

  it('reports disconnected once the stream is closed for good', () => {
    const { result } = renderHook(() => usePriceStream());

    act(() => MockEventSource.latest().fail(MockEventSource.CLOSED));

    expect(result.current.status).toBe('down');
  });

  it('recovers to live when ticks resume after a drop', () => {
    const { result } = renderHook(() => usePriceStream());
    const source = MockEventSource.latest();

    act(() => source.fail(MockEventSource.CONNECTING));
    act(() => source.emit(envelope(9, [tick('AAPL', 190)])));

    expect(result.current.status).toBe('live');
  });

  it('closes the connection on unmount', () => {
    const { unmount } = renderHook(() => usePriceStream());
    const source = MockEventSource.latest();

    unmount();

    expect(source.closed).toBe(true);
  });
});
