/** Display formatting. Every number in the terminal passes through here. */

export function money(value: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function signedMoney(value: number): string {
  return `${value < 0 ? '-' : '+'}${money(Math.abs(value))}`;
}

/** Takes a ratio (0.0123) and renders a percent (+1.23%). */
export function signedPercent(ratio: number): string {
  const pct = ratio * 100;
  return `${pct < 0 ? '-' : '+'}${Math.abs(pct).toFixed(2)}%`;
}

export function quantity(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '');
}

export function clockTime(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Split a formatted price into the leading digits that did not change and the
 * trailing run that did. Only the tail is flashed, so a one-cent move tints one
 * digit instead of strobing the whole row.
 */
export function splitChangedTail(next: string, previous: string | null): [string, string] {
  if (previous === null || previous.length !== next.length) return ['', next];
  let i = 0;
  while (i < next.length && next[i] === previous[i]) i += 1;
  return [next.slice(0, i), next.slice(i)];
}
