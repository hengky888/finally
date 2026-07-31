'use client';

import { useEffect, useRef, useState } from 'react';
import { apiUrl } from '@/lib/api';
import { applyEnvelope, emptyStream, parseEnvelope, type StreamState } from '@/lib/stream';
import type { ConnectionStatus } from '@/lib/types';

export interface PriceStream extends StreamState {
  status: ConnectionStatus;
}

/** Subscribe to `/api/stream/prices`. EventSource handles its own reconnection. */
export function usePriceStream(): PriceStream {
  const [state, setState] = useState<StreamState>(emptyStream);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(apiUrl('/api/stream/prices'));
    sourceRef.current = source;

    source.onopen = () => setStatus('live');

    source.onmessage = (event: MessageEvent<string>) => {
      const envelope = parseEnvelope(event.data);
      if (envelope) {
        setStatus('live');
        setState((current) => applyEnvelope(current, envelope));
      }
    };

    source.onerror = () => {
      setStatus(source.readyState === EventSource.CLOSED ? 'down' : 'connecting');
    };

    return () => source.close();
  }, []);

  return { ...state, status };
}
