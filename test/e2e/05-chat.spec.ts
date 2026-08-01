import { expect, test } from '@playwright/test';
import { closePositionIfOpen, openTerminal } from './helpers';

/**
 * Requires LLM_MOCK=true. The mock returns the same structured JSON the live
 * model would, so a mocked reply still executes a real trade.
 */
test.describe('AI assistant (mocked)', () => {
  test('answers a question', async ({ page }) => {
    await openTerminal(page);

    await page.getByTestId('chat-input').fill('How is my portfolio doing?');
    await page.getByTestId('chat-send').click();

    await expect(page.getByTestId('chat-message-0')).toHaveAttribute('data-role', 'user');
    const reply = page.getByTestId('chat-message-1');
    await expect(reply).toHaveAttribute('data-role', 'assistant');
    await expect(reply).toContainText('Mock analysis');
  });

  test('executes a trade and confirms it inline', async ({ page }) => {
    await openTerminal(page);
    await closePositionIfOpen(page, 'MSFT');

    await page.getByTestId('chat-input').fill('Buy 3 MSFT');
    await page.getByTestId('chat-send').click();

    const reply = page.getByTestId('chat-message-1');
    await expect(reply).toContainText('Executing a buy of 3 MSFT');

    // The inline action log is the confirmation of what actually filled.
    const actions = page.getByTestId('chat-actions-1');
    await expect(actions).toBeVisible();
    await expect(actions).toContainText('BUY');
    await expect(actions).toContainText('MSFT');

    // The trade is real: it lands in the portfolio, not just the transcript.
    await expect(page.getByTestId('positions-row-MSFT')).toBeVisible();
    await expect(page.getByTestId('position-qty-MSFT')).toHaveText('3');

    await closePositionIfOpen(page, 'MSFT');
  });
});
