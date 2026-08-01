import { expect, test } from '@playwright/test';
import { DEFAULT_TICKERS, openTerminal, waitForTick } from './helpers';

/**
 * Runs first, against a pristine database. Every later spec trades, so the
 * seeded $10,000 and empty portfolio are only observable here.
 */
test.describe('fresh start', () => {
  test('seeds the default watchlist, $10k cash and a live stream', async ({ page }) => {
    await openTerminal(page);

    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    }

    await expect(page.getByTestId('cash-balance')).toHaveText('10,000.00');
    await expect(page.getByTestId('total-value')).toHaveText('10,000.00');

    await expect(page.getByTestId('positions-empty')).toBeVisible();
    await expect(page.getByTestId('heatmap-empty')).toBeVisible();
  });

  test('streams prices into the watchlist', async ({ page }) => {
    await openTerminal(page);

    await expect(page.getByTestId('watchlist-price-AAPL')).not.toBeEmpty();
    await waitForTick(page);
    await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'live');
  });
});
