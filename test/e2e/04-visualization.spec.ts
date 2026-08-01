import { expect, test } from '@playwright/test';
import { closePositionIfOpen, openTerminal, placeOrder } from './helpers';

test.describe('portfolio visualization', () => {
  test('heatmap tiles render per position and the P&L chart has points', async ({ page }) => {
    await openTerminal(page);

    await placeOrder(page, 'buy', 'MSFT', 2);
    await placeOrder(page, 'buy', 'NVDA', 1);

    const msft = page.getByTestId('heatmap-tile-MSFT');
    const nvda = page.getByTestId('heatmap-tile-NVDA');
    await expect(msft).toBeVisible();
    await expect(nvda).toBeVisible();

    // Every tile is tinted by the sign of its unrealized P&L.
    await expect(msft).toHaveAttribute('data-pnl', /gain|loss/);
    await expect(page.getByTestId('heatmap-empty')).toHaveCount(0);

    // Each trade writes a snapshot, so the value series is populated by now.
    const plot = page.getByTestId('pnl-chart-plot');
    await expect(plot).toBeVisible();
    await expect
      .poll(async () => Number(await plot.getAttribute('data-points')), {
        message: 'P&L chart never received data points',
      })
      .toBeGreaterThan(0);

    await closePositionIfOpen(page, 'MSFT');
    await closePositionIfOpen(page, 'NVDA');
  });
});
