import { applyEnvelope, emptyStream, parseEnvelope } from './stream';
import { envelope, tick } from '@/test/factories';

describe('applyEnvelope', () => {
  it('records a ticker on first sight without counting a move', () => {
    const state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 190)]));

    expect(state.tickers.AAPL).toMatchObject({ price: 190, anchor: 190, moveSeq: 0 });
    expect(state.seq).toBe(1);
  });

  it('advances moveSeq on an up tick and a down tick', () => {
    let state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 190)]));
    state = applyEnvelope(state, envelope(2, [tick('AAPL', 191, 'up', 190)]));
    expect(state.tickers.AAPL.moveSeq).toBe(1);

    state = applyEnvelope(state, envelope(3, [tick('AAPL', 189, 'down', 191)]));
    expect(state.tickers.AAPL.moveSeq).toBe(2);
  });

  it('leaves moveSeq alone on a flat tick', () => {
    let state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 190)]));
    state = applyEnvelope(state, envelope(2, [tick('AAPL', 191, 'up', 190)]));
    const afterMove = state.tickers.AAPL.moveSeq;

    state = applyEnvelope(state, envelope(3, [tick('AAPL', 191, 'flat', 191)]));
    state = applyEnvelope(state, envelope(4, [tick('AAPL', 191, 'flat', 191)]));

    expect(state.tickers.AAPL.moveSeq).toBe(afterMove);
  });

  it('keeps the session anchor from the first tick', () => {
    let state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 100)]));
    state = applyEnvelope(state, envelope(2, [tick('AAPL', 120, 'up', 100)]));

    expect(state.tickers.AAPL.anchor).toBe(100);
  });

  it('accumulates a series point per tick, flat ones included', () => {
    let state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 190)]));
    state = applyEnvelope(state, envelope(2, [tick('AAPL', 190, 'flat', 190)]));
    state = applyEnvelope(state, envelope(3, [tick('AAPL', 191, 'up', 190)]));

    expect(state.series.AAPL.map((point) => point.p)).toEqual([190, 190, 191]);
  });

  it('caps the series and drops the oldest points', () => {
    let state = emptyStream;
    for (let i = 0; i < 5; i += 1) {
      state = applyEnvelope(state, envelope(i, [tick('AAPL', 100 + i)]), 3);
    }

    expect(state.series.AAPL.map((point) => point.p)).toEqual([102, 103, 104]);
  });

  it('drops tickers that left the priced set', () => {
    let state = applyEnvelope(emptyStream, envelope(1, [tick('AAPL', 190), tick('TSLA', 250)]));
    state = applyEnvelope(state, envelope(2, [tick('AAPL', 191, 'up', 190)]));

    expect(Object.keys(state.tickers)).toEqual(['AAPL']);
    expect(state.series.TSLA).toBeUndefined();
  });
});

describe('parseEnvelope', () => {
  it('parses a price envelope', () => {
    expect(parseEnvelope(JSON.stringify(envelope(7, [tick('AAPL', 190)])))?.seq).toBe(7);
  });

  it('ignores payloads that are not price envelopes', () => {
    expect(parseEnvelope('{"hello":"world"}')).toBeNull();
  });
});
