import type { ReactNode } from 'react';

interface PanelProps {
  label: string;
  /** Right-aligned live datum: panel headers report, they do not just title. */
  readout?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}

export function Panel({ label, readout, children, className = '', testId }: PanelProps) {
  return (
    <section className={`panel ${className}`} data-testid={testId}>
      <header className="panel-head">
        <h2 className="label text-[10px] text-muted">{label}</h2>
        {readout ? <div className="num text-[10px] text-dim">{readout}</div> : null}
      </header>
      {children}
    </section>
  );
}
