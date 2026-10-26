/**
 * BroadcastChannel in miniature, for tests: every open channel of a name hears
 * what the others post, never its own, a moment later — as the real one does.
 */
export class FakeChannel {
  static open = new Map<string, Set<FakeChannel>>();
  static posted: unknown[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(readonly name: string) {
    const peers = FakeChannel.open.get(name) ?? new Set();
    peers.add(this);
    FakeChannel.open.set(name, peers);
  }

  postMessage(data: unknown) {
    FakeChannel.posted.push(data);
    for (const peer of FakeChannel.open.get(this.name) ?? []) {
      if (peer !== this) queueMicrotask(() => peer.onmessage?.({ data } as MessageEvent));
    }
  }

  close() {
    FakeChannel.open.get(this.name)?.delete(this);
  }

  static reset() {
    FakeChannel.open.clear();
    FakeChannel.posted = [];
  }
}
