import { money, quantity, signedMoney, signedPercent, splitChangedTail } from './format';

describe('number formatting', () => {
  it('renders money with two decimals and thousands separators', () => {
    expect(money(12345.678)).toBe('12,345.68');
    expect(money(0)).toBe('0.00');
  });

  it('always signs P&L figures', () => {
    expect(signedMoney(120.5)).toBe('+120.50');
    expect(signedMoney(-120.5)).toBe('-120.50');
  });

  it('converts a ratio to a signed percent', () => {
    expect(signedPercent(0.0555)).toBe('+5.55%');
    expect(signedPercent(-0.1)).toBe('-10.00%');
  });

  it('keeps whole share counts whole', () => {
    expect(quantity(10)).toBe('10');
    expect(quantity(1.5)).toBe('1.5');
  });
});

describe('splitChangedTail', () => {
  it('isolates only the digits that moved', () => {
    expect(splitChangedTail('190.24', '190.21')).toEqual(['190.2', '4']);
  });

  it('splits at the first differing digit', () => {
    expect(splitChangedTail('191.24', '190.21')).toEqual(['19', '1.24']);
  });

  it('treats the whole value as changed on first render', () => {
    expect(splitChangedTail('190.24', null)).toEqual(['', '190.24']);
  });

  it('treats the whole value as changed when the digit count changes', () => {
    expect(splitChangedTail('1,000.00', '999.00')).toEqual(['', '1,000.00']);
  });
});
