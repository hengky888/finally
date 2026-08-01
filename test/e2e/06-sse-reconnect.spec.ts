import { expect, test } from '@playwright/test';
import { openTerminal, waitForTick } from './helpers';

const STREAM = '**/api/stream/prices';

test.describe('SSE resilience', () => {
  /**
   * `context.setOffline(true)` does not tear down an already-established
   * EventSource, so it never produces the error the UI reacts to. Cutting the
   * stream at the route level and reloading exercises the real path: the
   * indicator drops out of "live", EventSource retries on its own, and the
   * terminal recovers once the endpoint answers again.
   */
  test('reports a broken stream and recovers when it returns', async ({ page }) => {
    await openTerminal(page);
    await waitForTick(page);

    await page.route(STREAM, (route) => route.abort());
    await page.reload();

    await expect(page.getByTestId('connection-status')).toHaveAttribute(
      'data-status',
      /connecting|down/,
    );

    await page.unroute(STREAM);

    await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'live', {
      timeout: 30_000,
    });
    await waitForTick(page);
  });
});
