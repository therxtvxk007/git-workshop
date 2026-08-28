/**
 * A tiny seeded PRNG.
 *
 * The demo dataset must be byte-identical on every machine and every reload:
 * screenshots in the documentation have to match what a reader sees, and the
 * unit tests assert on specific districts. `Math.random()` would make the
 * fixtures untestable and the docs wrong within a week.
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Rng {
  private next: () => number;

  constructor(seed: number) {
    this.next = mulberry32(seed);
  }

  float(min = 0, max = 1): number {
    return min + this.next() * (max - min);
  }

  int(min: number, max: number): number {
    return Math.floor(this.float(min, max + 1));
  }

  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new Error("cannot pick from an empty list");
    return items[this.int(0, items.length - 1)] as T;
  }

  bool(probability = 0.5): boolean {
    return this.next() < probability;
  }
}

/** Deterministic pseudo-hash, so provenance chips look real and stay stable. */
export function fakeHash(prefix: string, ...parts: (string | number)[]): string {
  let h = 0x811c9dc5;
  for (const part of parts.join("|")) {
    h ^= part.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  const hex = h.toString(16).padStart(8, "0").repeat(4).slice(0, 32);
  return `${prefix}:${hex}`;
}
