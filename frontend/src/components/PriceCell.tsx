'use client';

import { useEffect, useRef, useState } from 'react';
import { money, splitChangedTail } from '@/lib/format';
import type { Direction } from '@/lib/types';

export const FLASH_MS = 520;

interface PriceCellProps {
  price: number;
  direction: Direction;
  /** Advances only on a genuine move — flat ticks leave it alone. */
  moveSeq: number;
  testId?: string;
  className?: string;
}

interface Flash {
  seq: number;
  head: string;
  tail: string;
  direction: Direction;
}

/**
 * The terminal's signature readout. On a real move only the digits that changed
 * are tinted, and the tint decays in ~500ms. Two ticks a second across a full
 * watchlist would strobe if the whole cell flashed, so it does not. The price
 * itself stays neutral; direction lives in the change column beside it.
 */
export function PriceCell({ price, direction, moveSeq, testId, className = '' }: PriceCellProps) {
  const text = money(price);
  const previousText = useRef<string | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);

  useEffect(() => {
    if (moveSeq === 0) return;
    const [head, tail] = splitChangedTail(text, previousText.current);
    previousText.current = text;
    setFlash({ seq: moveSeq, head, tail, direction });
    const timer = setTimeout(() => setFlash(null), FLASH_MS);
    return () => clearTimeout(timer);
    // The move counter is the sole trigger. Depending on `text` or `direction`
    // would re-fire the flash on flat ticks that merely re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moveSeq]);

  return (
    <span className={`num ${className}`} data-testid={testId} data-direction={direction}>
      {flash ? (
        <>
          {flash.head}
          <span
            key={flash.seq}
            className={flash.direction === 'down' ? 'tick-down' : 'tick-up'}
            data-testid={testId ? `${testId}-flash` : undefined}
            data-flash={flash.direction}
          >
            {flash.tail}
          </span>
        </>
      ) : (
        text
      )}
    </span>
  );
}
