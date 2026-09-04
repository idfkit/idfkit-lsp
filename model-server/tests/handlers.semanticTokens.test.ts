/**
 * Classification, translated (T035).
 *
 * `@idfkit/language` is not published, so every fixture here is a hand-written stand-in for what
 * the service would return. That is not a workaround: the handler is a pure translation, and a pure
 * translation is exactly the thing a fake result tests completely. A handler that needed the real
 * service to be tested would be a handler doing something besides translating.
 *
 * ON THE TOTALITY ASSERTION
 *
 * `contracts/model-server.md` point 3 requires classification to be total: regions cover the text
 * with no gaps and no overlaps, and concatenating what they select reproduces the input. That is a
 * property of the SERVICE'S ANSWER, and the test below asserts it OF THE FIXTURES, deliberately.
 * The handler neither checks nor enforces it. If the service ever hands back a gap, the gap is its
 * answer and the handler reports it as-is, because filling one would mean this repository deciding
 * what those characters are. `the gap is reported rather than filled` pins that.
 */

import { describe, expect, it } from 'vitest';

import { linePieces, semanticTokensFor, TokenLegend } from '../src/handlers/semanticTokens.js';
import { LineIndex } from '../src/positions.js';

import type { ClassifiedRegion } from '../src/language-service.js';
import type { SemanticTokensPayload } from '../src/handlers/semanticTokens.js';
import type { PositionEncoding } from '../src/positions.js';

/** One fixture: a text, and the regions the service is taken to have returned for it. */
interface Fixture {
  readonly what: string;
  readonly text: string;
  readonly regions: readonly ClassifiedRegion[];
}

/**
 * Regions are written as literal offsets rather than derived from the text, so that an assertion
 * that they tile the text is an assertion about something. Derived fixtures would tile by
 * construction and prove nothing.
 */
const PARSEABLE: Fixture = {
  what: 'text that parses',
  text: 'Version,26.1;\n',
  regions: [
    { start: 0, end: 7, kind: 'typeName' },
    { start: 7, end: 8, kind: 'separator' },
    { start: 8, end: 12, kind: 'value' },
    { start: 12, end: 13, kind: 'terminator' },
    { start: 13, end: 14, kind: 'trivia' },
  ],
};

/** A statement the writer has not finished. The normal case while typing, per FR-022. */
const UNTERMINATED: Fixture = {
  what: 'text missing a terminator',
  text: 'Zone,\n  Office\n',
  regions: [
    { start: 0, end: 4, kind: 'typeName' },
    { start: 4, end: 5, kind: 'separator' },
    // Crosses a line ending, which is the case the protocol's encoding cannot carry whole.
    { start: 5, end: 8, kind: 'trivia' },
    { start: 8, end: 14, kind: 'value' },
    { start: 14, end: 15, kind: 'trivia' },
  ],
};

/** Nothing states a version, so no schema could be chosen. Classification still covers the text. */
const NO_VERSION: Fixture = {
  what: 'text whose version cannot be determined',
  text: '! no version here\nBuilding,House;\n',
  regions: [
    { start: 0, end: 17, kind: 'comment' },
    { start: 17, end: 18, kind: 'trivia' },
    { start: 18, end: 26, kind: 'typeName' },
    { start: 26, end: 27, kind: 'separator' },
    { start: 27, end: 32, kind: 'value' },
    { start: 32, end: 33, kind: 'terminator' },
    { start: 33, end: 34, kind: 'trivia' },
  ],
};

/** Outside the basic plane, so a length that was measured in the wrong unit cannot pass. */
const ASTRAL: Fixture = {
  what: 'text outside the basic multilingual plane',
  text: 'Zone,A\u{1F600}B;\n',
  regions: [
    { start: 0, end: 4, kind: 'typeName' },
    { start: 4, end: 5, kind: 'separator' },
    { start: 5, end: 9, kind: 'value' },
    { start: 9, end: 10, kind: 'terminator' },
    { start: 10, end: 11, kind: 'trivia' },
  ],
};

const TOTAL: readonly Fixture[] = [PARSEABLE, UNTERMINATED, NO_VERSION, ASTRAL];

const TOKEN_WIDTH = 5;

interface DecodedToken {
  readonly kind: string;
  readonly start: number;
  readonly end: number;
}

/** Read the protocol's delta encoding back into offsets, which is what a client does. */
function decode(
  payload: SemanticTokensPayload,
  legend: TokenLegend,
  lines: LineIndex,
): DecodedToken[] {
  const tokens: DecodedToken[] = [];
  let line = 0;
  let character = 0;
  for (let cursor = 0; cursor < payload.data.length; cursor = cursor + TOKEN_WIDTH) {
    const deltaLine = payload.data[cursor] ?? 0;
    const deltaStart = payload.data[cursor + 1] ?? 0;
    const length = payload.data[cursor + 2] ?? 0;
    const type = payload.data[cursor + 3] ?? 0;
    line = line + deltaLine;
    character = deltaLine === 0 ? character + deltaStart : deltaStart;
    tokens.push({
      kind: legend.tokenTypes[type] ?? '',
      start: lines.offsetAt({ line, character }),
      end: lines.offsetAt({ line, character: character + length }),
    });
  }
  return tokens;
}

/** What the handler is expected to emit: every region cut at line endings, empties left out. */
function expectedPieces(fixture: Fixture, lines: LineIndex): DecodedToken[] {
  return [...fixture.regions]
    .sort((left, right) => left.start - right.start || left.end - right.end)
    .flatMap((region) => linePieces(region, lines))
    .map((piece) => ({ kind: piece.kind, start: piece.start, end: piece.end }));
}

function translate(fixture: Fixture, encoding: PositionEncoding = 'utf-16') {
  const lines = new LineIndex(fixture.text, encoding);
  const legend = new TokenLegend();
  return { lines, legend, payload: semanticTokensFor(fixture.regions, lines, legend) };
}

describe('the fixtures classify totally', () => {
  // Asserted of the fixtures, not of the handler. See the note at the top of this file.
  for (const fixture of TOTAL) {
    it(`covers ${fixture.what} with no gaps and no overlaps`, () => {
      let reached = 0;
      for (const region of fixture.regions) {
        expect(region.start).toBe(reached);
        expect(region.end).toBeGreaterThan(region.start);
        reached = region.end;
      }
      expect(reached).toBe(fixture.text.length);
    });

    it(`reproduces ${fixture.what} by concatenation`, () => {
      const rebuilt = fixture.regions
        .map((region) => fixture.text.slice(region.start, region.end))
        .join('');
      expect(rebuilt).toBe(fixture.text);
    });
  }
});

describe('nothing is added, dropped, merged, or reclassified', () => {
  for (const fixture of TOTAL) {
    it(`emits exactly the service's classification of ${fixture.what}`, () => {
      const { lines, legend, payload } = translate(fixture);
      expect(decode(payload, legend, lines)).toEqual(expectedPieces(fixture, lines));
    });

    it(`selects the same characters the service selected, for ${fixture.what}`, () => {
      const { lines, legend, payload } = translate(fixture);
      for (const token of decode(payload, legend, lines)) {
        expect(fixture.text.slice(token.start, token.end).length).toBeGreaterThan(0);
      }
      // A line ending carries no characters on the line it ends, so the only thing the handler
      // leaves out is a piece that would select nothing at all.
      const selected = decode(payload, legend, lines)
        .map((token) => fixture.text.slice(token.start, token.end))
        .join('');
      const withoutLineEndings = fixture.text.replace(/\r\n|\r|\n/g, '');
      expect(selected).toBe(withoutLineEndings);
    });
  }

  it('keeps a kind that the syntax layer has never used before', () => {
    const fixture: Fixture = {
      what: 'a kind this repository has never heard of',
      text: 'ab',
      regions: [{ start: 0, end: 2, kind: 'somethingEntirelyNew' }],
    };
    const { lines, legend, payload } = translate(fixture);
    expect(legend.tokenTypes).toEqual(['somethingEntirelyNew']);
    expect(decode(payload, legend, lines)[0]?.kind).toBe('somethingEntirelyNew');
  });
});

describe('the only reorder is the one the protocol requires', () => {
  it('puts the service’s regions into document order', () => {
    const shuffled: Fixture = {
      ...NO_VERSION,
      regions: [
        NO_VERSION.regions[4] as ClassifiedRegion,
        NO_VERSION.regions[0] as ClassifiedRegion,
        NO_VERSION.regions[6] as ClassifiedRegion,
        NO_VERSION.regions[2] as ClassifiedRegion,
        NO_VERSION.regions[1] as ClassifiedRegion,
        NO_VERSION.regions[5] as ClassifiedRegion,
        NO_VERSION.regions[3] as ClassifiedRegion,
      ],
    };
    expect(translate(shuffled).payload).toEqual(translate(NO_VERSION).payload);
  });

  it('emits tokens that never move backwards', () => {
    const { lines, legend, payload } = translate(NO_VERSION);
    const tokens = decode(payload, legend, lines);
    for (let position = 1; position < tokens.length; position = position + 1) {
      expect(tokens[position]?.start).toBeGreaterThanOrEqual(tokens[position - 1]?.end ?? 0);
    }
  });
});

describe('a gap is reported rather than filled', () => {
  const GAPPED: Fixture = {
    what: 'a classification with a hole in it',
    text: 'Version,26.1;\n',
    regions: [
      { start: 0, end: 7, kind: 'typeName' },
      // 7 through 12 is missing. The service said nothing about it, so neither does the handler.
      { start: 12, end: 13, kind: 'terminator' },
    ],
  };

  it('emits the regions it was given and no others', () => {
    const { lines, legend, payload } = translate(GAPPED);
    expect(decode(payload, legend, lines)).toEqual([
      { kind: 'typeName', start: 0, end: 7 },
      { kind: 'terminator', start: 12, end: 13 },
    ]);
  });

  it('does not reproduce the text, which is the service’s answer and not the handler’s', () => {
    const { lines, legend, payload } = translate(GAPPED);
    const selected = decode(payload, legend, lines)
      .map((token) => GAPPED.text.slice(token.start, token.end))
      .join('');
    expect(selected).not.toBe(GAPPED.text);
  });
});

describe('the legend is the service’s vocabulary and not this repository’s', () => {
  it('holds nothing until the service names something', () => {
    const legend = new TokenLegend();
    expect(legend.tokenTypes).toEqual([]);
    expect(legend.tokenModifiers).toEqual([]);
    expect(legend.generation).toBe(0);
  });

  it('admits each kind once, in the order the service first used it', () => {
    const { legend } = translate(NO_VERSION);
    // No `trivia`: both trivia regions in this fixture are a line ending on its own, and a line
    // ending selects no characters on the line it ends, so no token is emitted for either. A kind
    // reaches the legend when a token carries it and not before.
    expect(legend.tokenTypes).toEqual([
      'comment',
      'typeName',
      'separator',
      'value',
      'terminator',
    ]);
    expect(legend.generation).toBe(legend.tokenTypes.length);
  });

  it('reports no modifier, because the service reports none', () => {
    const { payload } = translate(PARSEABLE);
    for (let cursor = 4; cursor < payload.data.length; cursor = cursor + TOKEN_WIDTH) {
      expect(payload.data[cursor]).toBe(0);
    }
  });
});

describe('positions round trip outside the basic multilingual plane', () => {
  const ENCODINGS: readonly PositionEncoding[] = ['utf-8', 'utf-16', 'utf-32'];

  for (const encoding of ENCODINGS) {
    it(`selects the same characters in ${encoding}`, () => {
      const { lines, legend, payload } = translate(ASTRAL, encoding);
      const selected = decode(payload, legend, lines).map((token) =>
        ASTRAL.text.slice(token.start, token.end),
      );
      expect(selected).toEqual(['Zone', ',', 'A\u{1F600}B', ';']);
    });
  }

  it('measures a token’s length in the unit that was negotiated', () => {
    // The value spans 'A', a four-byte two-code-unit one-code-point emoji, and 'B'.
    const lengths = ENCODINGS.map((encoding) => translate(ASTRAL, encoding).payload.data[12]);
    expect(lengths).toEqual([6, 4, 3]);
  });
});
