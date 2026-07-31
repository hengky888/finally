'use client';

import { useCallback, useState } from 'react';
import { sendChat } from '@/lib/api';
import type { ChatMessage } from '@/lib/types';

export interface Chat {
  messages: ChatMessage[];
  pending: boolean;
  send: (text: string) => Promise<void>;
}

/**
 * Conversation state. History lives in the browser for the session; the backend
 * keeps its own copy for LLM context and exposes no history endpoint.
 */
export function useChat(onActed: () => Promise<void>): Chat {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);

  const send = useCallback(
    async (text: string) => {
      setMessages((current) => [...current, { role: 'user', content: text }]);
      setPending(true);
      try {
        const response = await sendChat(text);
        setMessages((current) => [
          ...current,
          { role: 'assistant', content: response.message, actions: response.actions },
        ]);
        await onActed();
      } catch (cause) {
        setMessages((current) => [
          ...current,
          {
            role: 'assistant',
            content: cause instanceof Error ? cause.message : 'The assistant is unreachable.',
          },
        ]);
      } finally {
        setPending(false);
      }
    },
    [onActed],
  );

  return { messages, pending, send };
}
