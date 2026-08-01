import { squarify } from './treemap';

const BOX = { x: 0, y: 0, width: 100, height: 100 };

describe('squarify', () => {
  it('gives a single item the whole rectangle', () => {
    const [tile] = squarify([{ key: 'AAPL', value: 1 }], BOX);

    expect(tile).toMatchObject({ key: 'AAPL', x: 0, y: 0, width: 100, height: 100 });
  });

  it('allocates area in proportion to value', () => {
    const tiles = squarify(
      [
        { key: 'BIG', value: 75 },
        { key: 'SMALL', value: 25 },
      ],
      BOX,
    );
    const area = (key: string) => {
      const tile = tiles.find((t) => t.key === key)!;
      return tile.width * tile.height;
    };

    expect(area('BIG')).toBeCloseTo(7500, 4);
    expect(area('SMALL')).toBeCloseTo(2500, 4);
  });

  it('covers the rectangle exactly', () => {
    const tiles = squarify(
      [
        { key: 'A', value: 40 },
        { key: 'B', value: 30 },
        { key: 'C', value: 20 },
        { key: 'D', value: 10 },
      ],
      BOX,
    );
    const total = tiles.reduce((sum, tile) => sum + tile.width * tile.height, 0);

    expect(tiles).toHaveLength(4);
    expect(total).toBeCloseTo(10_000, 3);
  });

  it('drops non-positive values and empty input', () => {
    expect(squarify([{ key: 'A', value: 0 }], BOX)).toEqual([]);
    expect(squarify([], BOX)).toEqual([]);
  });
});
