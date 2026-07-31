import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import type { ChatMessage } from '@/lib/types';

const conversation: ChatMessage[] = [
  { role: 'user', content: 'Buy 5 AAPL' },
  {
    role: 'assistant',
    content: 'Bought 5 AAPL and started watching PYPL.',
    actions: {
      trades: [{ ticker: 'AAPL', side: 'buy', quantity: 5, price: 190.12 }],
      watchlist_changes: [{ ticker: 'PYPL', action: 'add' }],
      errors: ['Insufficient cash to buy 10 TSLA'],
    },
  },
];

function setup(overrides: Partial<Parameters<typeof ChatPanel>[0]> = {}) {
  const props = {
    messages: conversation,
    pending: false,
    onSend: jest.fn().mockResolvedValue(undefined),
    onCollapse: jest.fn(),
    ...overrides,
  };
  render(<ChatPanel {...props} />);
  return props;
}

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

describe('ChatPanel', () => {
  it('renders the conversation in order with roles', () => {
    setup();

    expect(screen.getByTestId('chat-message-0')).toHaveAttribute('data-role', 'user');
    expect(screen.getByTestId('chat-message-0')).toHaveTextContent('Buy 5 AAPL');
    expect(screen.getByTestId('chat-message-1')).toHaveAttribute('data-role', 'assistant');
  });

  it('confirms executed trades inline', () => {
    setup();

    expect(screen.getByTestId('chat-actions-1')).toHaveTextContent('BUY 5 AAPL @ 190.12');
  });

  it('confirms watchlist changes inline', () => {
    setup();

    expect(screen.getByTestId('chat-actions-1')).toHaveTextContent('WATCH +PYPL');
  });

  it('shows rejections the assistant reported', () => {
    setup();

    expect(screen.getByTestId('chat-actions-1')).toHaveTextContent(
      'Insufficient cash to buy 10 TSLA',
    );
  });

  it('omits the action log when nothing was executed', () => {
    setup({ messages: [{ role: 'assistant', content: 'Your portfolio looks balanced.' }] });

    expect(screen.queryByTestId('chat-actions-0')).not.toBeInTheDocument();
  });

  it('shows a loading indicator while the assistant is thinking', () => {
    setup({ pending: true });

    expect(screen.getByTestId('chat-loading')).toBeInTheDocument();
  });

  it('hides the loading indicator when idle', () => {
    setup();

    expect(screen.queryByTestId('chat-loading')).not.toBeInTheDocument();
  });

  it('sends the message and clears the input', async () => {
    const props = setup();
    const input = screen.getByTestId('chat-input');

    await userEvent.type(input, 'How am I doing?');
    await userEvent.click(screen.getByTestId('chat-send'));

    expect(props.onSend).toHaveBeenCalledWith('How am I doing?');
    expect(input).toHaveValue('');
  });

  it('will not send while a response is pending', async () => {
    const props = setup({ pending: true });

    await userEvent.type(screen.getByTestId('chat-input'), 'again{Enter}');

    expect(props.onSend).not.toHaveBeenCalled();
  });

  it('will not send an empty message', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('chat-send'));

    expect(props.onSend).not.toHaveBeenCalled();
  });

  it('prompts the user when the conversation is empty', () => {
    setup({ messages: [] });

    expect(screen.getByTestId('chat-empty')).toBeInTheDocument();
  });

  it('collapses on request', async () => {
    const props = setup();

    await userEvent.click(screen.getByTestId('chat-collapse'));

    expect(props.onCollapse).toHaveBeenCalled();
  });
});
