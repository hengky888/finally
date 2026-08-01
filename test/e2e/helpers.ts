import { expect, type Page } from '@playwright/test';

/** Seeded on a fresh database, from backend/app/market/seed_prices.py. */
export const DEFAULT_TICKERS = [
  'AAPL',
  'GOOGL',
  'MSFT',
  'AMZN',
  'TSLA',
  'NVDA',
  'META',
  'JPM',
  'V',
  'NFLX',
];

const pathIs = (path: string) => (response: { url(): string; ok(): boolean }) =>
  new URL(response.url()).pathname === path && response.ok();

/**
 * Open the terminal and wait until it is genuinely usable.
 *
 * The price stream and the account state load independently: `usePortfolio`
 * starts at a cash balance of 0 and fills in when `/api/portfolio` resolves,
 * which can land after the stream is already live. Waiting only on the
 * connection indicator therefore races, so wait on those responses too.
 */
export async function openTerminal(page: Page): Promise<void> {
  const portfolio = page.waitForResponse(pathIs('/api/portfolio'));
  const watchlist = page.waitForResponse(pathIs('/api/watchlist'));
  await page.goto('/');
  await Promise.all([portfolio, watchlist]);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'live');
}

/** "9,810.40" / "+1,234.00" -> number. The UI formats with commas and a sign. */
export function parseMoney(text: string): number {
  return Number.parseFloat(text.replace(/,/g, '').replace(/[^0-9.-]/g, ''));
}

export async function readMoney(page: Page, testId: string): Promise<number> {
  return parseMoney(await page.getByTestId(testId).innerText());
}

/** Current stream sequence number from the "TICK n" readout. */
export async function readSeq(page: Page): Promise<number> {
  const text = await page.getByTestId('stream-seq').innerText();
  return Number.parseInt(text.replace(/\D/g, ''), 10);
}

/**
 * Wait for the stream to deliver at least one further update. Waits on the
 * sequence number actually advancing rather than on a fixed delay.
 */
export async function waitForTick(page: Page): Promise<void> {
  const start = await readSeq(page);
  await expect
    .poll(() => readSeq(page), { message: 'stream sequence did not advance' })
    .toBeGreaterThan(start);
}

/** Submit a market order through the trade bar and wait for the fill. */
export async function placeOrder(
  page: Page,
  side: 'buy' | 'sell',
  ticker: string,
  quantity: number,
): Promise<void> {
  await page.getByTestId('trade-ticker-input').fill(ticker);
  await page.getByTestId('trade-quantity-input').fill(String(quantity));
  await page.getByTestId(side === 'buy' ? 'trade-buy-button' : 'trade-sell-button').click();

  const status = page.getByTestId('trade-status');
  await expect(status).toHaveAttribute('data-tone', 'ok');
  await expect(status).toContainText(`Filled ${side} ${quantity} ${ticker}`);
}

/** Close a position if the suite left one open, so specs start from a known state. */
export async function closePositionIfOpen(page: Page, ticker: string): Promise<void> {
  const row = page.getByTestId(`positions-row-${ticker}`);
  if ((await row.count()) === 0) return;
  const held = Number.parseFloat(await page.getByTestId(`position-qty-${ticker}`).innerText());
  if (held > 0) await placeOrder(page, 'sell', ticker, held);
}
