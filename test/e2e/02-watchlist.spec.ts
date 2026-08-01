import { expect, test } from '@playwright/test';
import { openTerminal } from './helpers';

const SYMBOL = 'ORCL';

test.describe('watchlist', () => {
  test('adds and removes a ticker', async ({ page }) => {
    await openTerminal(page);

    await page.getByTestId('watchlist-add-input').fill(SYMBOL);
    await page.getByTestId('watchlist-add-submit').click();

    const row = page.getByTestId(`watchlist-row-${SYMBOL}`);
    await expect(row).toBeVisible();
    await expect(page.getByTestId(`watchlist-price-${SYMBOL}`)).not.toBeEmpty();

    await page.getByTestId(`watchlist-remove-${SYMBOL}`).click();
    await expect(row).toHaveCount(0);
  });

  test('rejects a symbol the market source does not know', async ({ page }) => {
    await openTerminal(page);

    await page.getByTestId('watchlist-add-input').fill('ZZZZ');
    await page.getByTestId('watchlist-add-submit').click();

    await expect(page.getByTestId('watchlist-add-error')).toBeVisible();
    await expect(page.getByTestId('watchlist-row-ZZZZ')).toHaveCount(0);
  });
});
