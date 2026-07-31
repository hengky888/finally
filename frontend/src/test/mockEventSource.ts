/** Minimal EventSource stand-in: jsdom has none, and tests need to drive ticks. */
export class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: MockEventSource[] = [];

  readyState = MockEventSource.CONNECTING;
  closed = false;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    MockEventSource.instances.push(this);
  }

  close() {
    this.readyState = MockEventSource.CLOSED;
    this.closed = true;
  }

  /** Simulate the server accepting the connection. */
  open() {
    this.readyState = MockEventSource.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** Push one SSE payload. */
  emit(payload: unknown) {
    this.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(payload) }) as MessageEvent<string>,
    );
  }

  /** Simulate a transport error, either retrying or permanently closed. */
  fail(readyState: number = MockEventSource.CONNECTING) {
    this.readyState = readyState;
    this.onerror?.(new Event('error'));
  }

  static latest(): MockEventSource {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }

  static install() {
    MockEventSource.instances = [];
    (globalThis as unknown as { EventSource: unknown }).EventSource = MockEventSource;
  }
}
