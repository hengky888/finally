import { expect, test } from '@playwright/test';
import { closePositionIfOpen, openTerminal, placeOrder, readMoney } from './helpers';

const SYMBOL = 'AAPL';
const SHARES = 5;

test.describe('trading', () => {
  test('buying debits cash and opens a position', async ({ page }) => {
    await openTerminal(page);
    await closePositionIfOpen(page, SYMBOL);

    const cashBefore = await readMoney(page, 'cash-balance');
    await placeOrder(page, 'buy', SYMBOL, SHARES);

    await expect(page.getByTestId(`positions-row-${SYMBOL}`)).toBeVisible();
    await expect(page.getByTestId(`position-qty-${SYMBOL}`)).toHaveText(String(SHARES));

    const cashAfter = await readMoney(page, 'cash-balance');
    expect(cashAfter).toBeLessThan(cashBefore);

    // Cash moved by roughly the notional; prices tick, so allow a small drift.
    const avgCost = await readMoney(page, `position-avg-cost-${SYMBOL}`);
    expect(cashBefore - cashAfter).toBeCloseTo(avgCost * SHARES, 1);
  });

  test('selling the whole position credits cash and clears the row', async ({ page }) => {
    await openTerminal(page);

    // Ensure there is something to sell regardless of how the previous test ended.
    if ((await page.getByTestId(`positions-row-${SYMBOL}`).count()) === 0) {
      await placeOrder(page, 'buy', SYMBOL, SHARES);
    }
    const held = Number.parseFloat(await page.getByTestId(`position-qty-${SYMBOL}`).innerText());
    const cashBefore = await readMoney(page, 'cash-balance');

    await placeOrder(page, 'sell', SYMBOL, held);

    await expect(page.getByTestId(`positions-row-${SYMBOL}`)).toHaveCount(0);
    expect(await readMoney(page, 'cash-balance')).toBeGreaterThan(cashBefore);
  });

  test('rejects a sell of shares that are not held', async ({ page }) => {
    await openTerminal(page);
    await closePositionIfOpen(page, SYMBOL);

    await page.getByTestId('trade-ticker-input').fill(SYMBOL);
    await page.getByTestId('trade-quantity-input').fill('999');
    await page.getByTestId('trade-sell-button').click();

    await expect(page.getByTestId('trade-status')).toHaveAttribute('data-tone', 'error');
    await expect(page.getByTestId(`positions-row-${SYMBOL}`)).toHaveCount(0);
  });
});
