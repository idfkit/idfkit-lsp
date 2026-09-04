import { describe, expect, it } from 'vitest';

import { LineIndex } from '../src/positions.js';
import type { PositionEncoding } from '../src/positions.js';

const ENCODINGS: readonly PositionEncoding[] = ['utf-8', 'utf-16', 'utf-32'];

/**
 * Deliberately not ASCII: an emoji and a musical symbol both sit outside the basic multilingual
 * plane, so every offset past them differs between the three encodings. A round trip over ASCII
 * would pass for all three implementations even if two of them were wrong.
 */
const ASTRAL = 'a\u{1F600}b\n\u{1D11E} x\ny';

/**
 * Offsets a round trip must preserve: the start of every character, minus the tail half of a CRLF,
 * which is inside a line terminator and therefore clamps to the line end by design.
 */
function roundTrippableOffsets(text: string): number[] {
  const offsets: number[] = [];
  let offset = 0;
  while (offset < text.length) {
    const isCrlfTail = text.charCodeAt(offset) === 10 && text.charCodeAt(offset - 1) === 13;
    if (!isCrlfTail) offsets.push(offset);
    offset += (text.codePointAt(offset) ?? 0) > 0xffff ? 2 : 1;
  }
  offsets.push(text.length);
  return offsets;
}

describe('round tripping outside the basic multilingual plane', () => {
  for (const encoding of ENCODINGS) {
    it(`offset -> position -> offset is the identity in ${encoding}`, () => {
      const index = new LineIndex(ASTRAL, encoding);
      for (const offset of roundTrippableOffsets(ASTRAL)) {
        expect(index.offsetAt(index.positionAt(offset))).toBe(offset);
      }
    });
  }

  it('measures a line prefix in the unit that was negotiated', () => {
    // Offset 3 is just past 'a' and the emoji: one ASCII byte plus a four-byte, two-code-unit,
    // one-code-point character.
    expect(new LineIndex(ASTRAL, 'utf-8').positionAt(3)).toEqual({ line: 0, character: 5 });
    expect(new LineIndex(ASTRAL, 'utf-16').positionAt(3)).toEqual({ line: 0, character: 3 });
    expect(new LineIndex(ASTRAL, 'utf-32').positionAt(3)).toEqual({ line: 0, character: 2 });
  });

  it('measures a three-byte astral lead the same way on a later line', () => {
    // The musical symbol opens line 1; the offset just past it is 7.
    expect(new LineIndex(ASTRAL, 'utf-8').positionAt(7)).toEqual({ line: 1, character: 4 });
    expect(new LineIndex(ASTRAL, 'utf-16').positionAt(7)).toEqual({ line: 1, character: 2 });
    expect(new LineIndex(ASTRAL, 'utf-32').positionAt(7)).toEqual({ line: 1, character: 1 });
  });

  it('never splits a surrogate pair from either direction', () => {
    for (const encoding of ENCODINGS) {
      const index = new LineIndex(ASTRAL, encoding);
      // Offset 2 is between the halves of the emoji: it resolves to the character's start.
      expect(index.positionAt(2)).toEqual(index.positionAt(1));
      expect(index.offsetAt(index.positionAt(2))).toBe(1);
    }
    // A character count landing inside the emoji resolves to the emoji's start, per encoding.
    expect(new LineIndex(ASTRAL, 'utf-16').offsetAt({ line: 0, character: 2 })).toBe(1);
    expect(new LineIndex(ASTRAL, 'utf-8').offsetAt({ line: 0, character: 3 })).toBe(1);
  });
});

describe('line endings', () => {
  it('splits LF-only text', () => {
    const index = new LineIndex('alpha\nbeta\ngamma');
    expect(index.lineCount).toBe(3);
    expect(index.positionAt(6)).toEqual({ line: 1, character: 0 });
    expect(index.offsetAt({ line: 2, character: 0 })).toBe(11);
  });

  it('treats a CRLF as one line ending and not two', () => {
    const text = 'alpha\r\nbeta\r\ngamma';
    const index = new LineIndex(text);
    expect(index.lineCount).toBe(3);
    expect(index.positionAt(7)).toEqual({ line: 1, character: 0 });
    expect(index.offsetAt({ line: 1, character: 0 })).toBe(7);
    // The CR ends the line, so an offset on it reports the line's end rather than a longer line.
    expect(index.positionAt(5)).toEqual({ line: 0, character: 5 });
    expect(index.positionAt(6)).toEqual({ line: 0, character: 5 });
  });

  it('ends a line on a lone CR', () => {
    const index = new LineIndex('alpha\rbeta');
    expect(index.lineCount).toBe(2);
    expect(index.positionAt(6)).toEqual({ line: 1, character: 0 });
    expect(index.offsetAt({ line: 1, character: 4 })).toBe(10);
  });

  it('handles text mixing LF, CRLF and a lone CR', () => {
    const text = 'a\nb\r\nc\rd';
    const index = new LineIndex(text);
    expect(index.lineCount).toBe(4);
    expect(index.positionAt(0)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(2)).toEqual({ line: 1, character: 0 });
    expect(index.positionAt(5)).toEqual({ line: 2, character: 0 });
    expect(index.positionAt(7)).toEqual({ line: 3, character: 0 });
    for (const encoding of ENCODINGS) {
      const encoded = new LineIndex(text, encoding);
      for (const offset of roundTrippableOffsets(text)) {
        expect(encoded.offsetAt(encoded.positionAt(offset))).toBe(offset);
      }
    }
  });

  it('round trips astral text using CRLF', () => {
    const text = 'a\u{1F600}b\r\n\u{1D11E} x\r\ny';
    for (const encoding of ENCODINGS) {
      const index = new LineIndex(text, encoding);
      for (const offset of roundTrippableOffsets(text)) {
        expect(index.offsetAt(index.positionAt(offset))).toBe(offset);
      }
    }
  });
});

describe('rangeOf', () => {
  it('selects exactly the intended substring', () => {
    const region = { start: 5, end: 9 };
    expect(ASTRAL.slice(region.start, region.end)).toBe('\u{1D11E} x');

    const index = new LineIndex(ASTRAL, 'utf-16');
    const range = index.rangeOf(region);
    expect(range).toEqual({
      start: { line: 1, character: 0 },
      end: { line: 1, character: 4 },
    });
    expect(index.offsetAt(range.start)).toBe(region.start);
    expect(index.offsetAt(range.end)).toBe(region.end);
  });

  it('recomputes the same offsets in every encoding', () => {
    const region = { start: 1, end: 3 };
    expect(ASTRAL.slice(region.start, region.end)).toBe('\u{1F600}');
    for (const encoding of ENCODINGS) {
      const index = new LineIndex(ASTRAL, encoding);
      const range = index.rangeOf(region);
      expect(index.offsetAt(range.start)).toBe(region.start);
      expect(index.offsetAt(range.end)).toBe(region.end);
    }
  });

  it('spans lines when the region does', () => {
    const index = new LineIndex(ASTRAL, 'utf-16');
    const range = index.rangeOf({ start: 3, end: 7 });
    expect(range).toEqual({
      start: { line: 0, character: 3 },
      end: { line: 1, character: 2 },
    });
  });
});

describe('clamping', () => {
  const index = new LineIndex(ASTRAL, 'utf-16');

  it('clamps an offset above the end to the end of the text', () => {
    expect(index.positionAt(ASTRAL.length + 500)).toEqual({ line: 2, character: 1 });
    expect(index.positionAt(Number.POSITIVE_INFINITY)).toEqual({ line: 2, character: 1 });
  });

  it('clamps an offset below zero to the start of the text', () => {
    expect(index.positionAt(-1)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(Number.NEGATIVE_INFINITY)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(Number.NaN)).toEqual({ line: 0, character: 0 });
  });

  it('clamps a character past the end of its line to the line end', () => {
    expect(index.offsetAt({ line: 0, character: 999 })).toBe(4);
    expect(index.offsetAt({ line: 1, character: 999 })).toBe(9);
    expect(index.offsetAt({ line: 0, character: -3 })).toBe(0);
  });

  it('clamps a line outside the text to the nearest end', () => {
    expect(index.offsetAt({ line: 99, character: 0 })).toBe(ASTRAL.length);
    expect(index.offsetAt({ line: -4, character: 2 })).toBe(0);
  });

  it('never throws on a degenerate range', () => {
    expect(index.rangeOf({ start: 40, end: -40 })).toEqual({
      start: { line: 2, character: 1 },
      end: { line: 0, character: 0 },
    });
  });
});

describe('degenerate documents', () => {
  it('handles an empty document', () => {
    const index = new LineIndex('');
    expect(index.lineCount).toBe(1);
    expect(index.positionAt(0)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(7)).toEqual({ line: 0, character: 0 });
    expect(index.offsetAt({ line: 0, character: 0 })).toBe(0);
    expect(index.offsetAt({ line: 5, character: 5 })).toBe(0);
    expect(index.rangeOf({ start: 0, end: 0 })).toEqual({
      start: { line: 0, character: 0 },
      end: { line: 0, character: 0 },
    });
  });

  it('handles a document that is a single newline', () => {
    const index = new LineIndex('\n');
    expect(index.lineCount).toBe(2);
    expect(index.positionAt(0)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(1)).toEqual({ line: 1, character: 0 });
    expect(index.offsetAt({ line: 0, character: 5 })).toBe(0);
    expect(index.offsetAt({ line: 1, character: 0 })).toBe(1);
  });

  it('handles a document that is a single CRLF', () => {
    const index = new LineIndex('\r\n');
    expect(index.lineCount).toBe(2);
    expect(index.positionAt(1)).toEqual({ line: 0, character: 0 });
    expect(index.positionAt(2)).toEqual({ line: 1, character: 0 });
    expect(index.offsetAt({ line: 1, character: 0 })).toBe(2);
  });
});
