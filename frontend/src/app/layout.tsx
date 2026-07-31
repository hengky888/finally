import type { Metadata, Viewport } from 'next';
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Condensed } from 'next/font/google';
import './globals.css';

// One superfamily, three voices: condensed for instrument labels, mono for every
// number, sans for the assistant's prose.
const condensed = IBM_Plex_Sans_Condensed({
  subsets: ['latin'],
  weight: ['500', '600'],
  variable: '--font-plex-condensed',
});

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-plex-mono',
});

const sans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-plex-sans',
});

export const metadata: Metadata = {
  title: 'FinAlly - AI Trading Workstation',
  description: 'Live market data, a simulated portfolio, and an AI copilot that trades.',
};

export const viewport: Viewport = {
  themeColor: '#0d1117',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${condensed.variable} ${mono.variable} ${sans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
