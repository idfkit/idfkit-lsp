/**
 * The schema explanation at an offset, translated (T045, T049), and where a name is declared
 * (T050).
 *
 * The definition assertions live here rather than in a file of their own because the task list
 * allocates no test file for them, and the two answers are the same shape: a cursor question the
 * service answers or declines, translated by a pure function, with the declining case the one worth
 * pinning. Splitting them into a file nobody owns would risk two agents claiming one path.
 *
 * WHAT THE HOVER TESTS ARE REALLY ABOUT
 *
 * On whitespace, on a separator, and inside a comment the service answers `notApplicable`, and the
 * only correct hover there is none. Reporting the nearest field instead is the behaviour that makes
 * a hover feel haunted: it looks right in a screenshot and teaches a reader something false about
 * where their cursor is. The handler cannot do it, because it never sees a neighbour, and these
 * assertions are what keep that true as the file changes.
 */

import { describe, expect, it } from 'vitest';

import { definitionFor } from '../src/handlers/definition.js';
import { hoverFor } from '../src/handlers/hover.js';
import { LineIndex } from '../src/positions.js';

import type { Declaration, Explanation } from '../src/language-service.js';

const TEXT = 'Zone,\n  Office,   ! the name\n  3.0;\nZone,\n  Office2;\n';
const URI = 'file:///model.idf';
const lines = () => new LineIndex(TEXT, 'utf-16');

const FIELD_REGION = { start: 31, end: 34 };

const EXPLAINED: Explanation = {
  region: FIELD_REGION,
  of: 'field',
  typeName: 'Zone',
  fieldName: 'ceiling_height',
  prose: 'the schema own words, reproduced and never paraphrased',
  field: {},
  docs: undefined,
};

describe('an explanation the service produced', () => {
  it('highlights the region the service said it describes', () => {
    const index = lines();
    const answer = hoverFor({ status: 'ok', explanation: EXPLAINED }, index);
    if (answer.kind !== 'hover') throw new Error('expected a hover');
    expect(answer.hover.range).toEqual(index.rangeOf(FIELD_REGION));
    expect(TEXT.slice(FIELD_REGION.start, FIELD_REGION.end)).toBe('3.0');
  });

  it('reproduces the schema prose without rewording it', () => {
    const answer = hoverFor({ status: 'ok', explanation: EXPLAINED }, lines());
    if (answer.kind !== 'hover') throw new Error('expected a hover');
    const contents = answer.hover.contents as { kind: string; value: string };
    expect(contents.kind).toBe('markdown');
    expect(contents.value).toContain(EXPLAINED.prose);
    expect(contents.value).toContain(EXPLAINED.typeName);
    expect(contents.value).toContain('ceiling_height');
  });

  it('derives no prose from a name where the bundle carries none', () => {
    const bare: Explanation = { ...EXPLAINED, prose: undefined };
    const answer = hoverFor({ status: 'ok', explanation: bare }, lines());
    if (answer.kind !== 'hover') throw new Error('expected a hover');
    const contents = answer.hover.contents as { value: string };
    // Exactly the two names the service gave, and not one sentence more.
    expect(contents.value).toBe('`Zone`\n\n`ceiling_height`');
  });

  it('names only the type where the explanation is about a type', () => {
    const onType: Explanation = { ...EXPLAINED, of: 'objectType', fieldName: undefined };
    const answer = hoverFor({ status: 'ok', explanation: onType }, lines());
    if (answer.kind !== 'hover') throw new Error('expected a hover');
    const contents = answer.hover.contents as { value: string };
    expect(contents.value).toBe(`\`Zone\`\n\n${EXPLAINED.prose ?? ''}`);
  });
});

describe('nothing, rather than the nearest field', () => {
  /**
   * The three positions `contracts/language-service.md` names for `notApplicable`. The offsets are
   * recorded so the fixture stays a real file rather than a label, even though the handler is given
   * the service answer for each rather than the offset.
   */
  const NOT_APPLICABLE: readonly (readonly [string, number])[] = [
    ['whitespace between a field and its statement', 6],
    ['a separator', 4],
    ['a comment', 20],
  ];

  for (const [what, offset] of NOT_APPLICABLE) {
    it(`returns nothing on ${what}`, () => {
      const answer = hoverFor({ status: 'notApplicable' }, lines());
      expect(answer.kind).toBe('nothing');
      if (answer.kind !== 'nothing') return;
      expect(answer.absence).toEqual({ kind: 'permitsNothing', reason: 'notApplicable' });
      // The offset is inside the text and next to a field that does have an explanation, which is
      // exactly the field a substituting handler would have reached for.
      expect(offset).toBeLessThan(TEXT.length);
    });
  }

  it('returns no hover object at all, not an empty one', () => {
    const answer = hoverFor({ status: 'notApplicable' }, lines());
    expect(Object.hasOwn(answer, 'hover')).toBe(false);
  });

  it('returns nothing where no schema could be consulted, and says why', () => {
    const answer = hoverFor({ status: 'noSchema' }, lines());
    if (answer.kind !== 'nothing') throw new Error('expected an absence');
    expect(answer.absence).toEqual({
      kind: 'cannotAnswer',
      reason: 'noSchema',
      typeName: undefined,
    });
  });

  it('returns nothing where the schema constrains nothing, and keeps that apart', () => {
    const answer = hoverFor({ status: 'unconstrained' }, lines());
    if (answer.kind !== 'nothing') throw new Error('expected an absence');
    expect(answer.absence).toEqual({ kind: 'constrainsNothing' });
  });

  it('returns nothing where the type the text wrote is not in the schema', () => {
    const answer = hoverFor({ status: 'unknownType', typeName: 'Zne' }, lines());
    if (answer.kind !== 'nothing') throw new Error('expected an absence');
    expect(answer.absence).toEqual({
      kind: 'cannotAnswer',
      reason: 'unknownType',
      typeName: 'Zne',
    });
  });
});

describe('every declaration the service reports, never one chosen here', () => {
  const FIRST: Declaration = { region: { start: 8, end: 14 }, typeName: 'Zone' };
  const SECOND: Declaration = { region: { start: 44, end: 51 }, typeName: 'Zone' };

  it('returns all of them when a name is declared more than once', () => {
    const index = lines();
    const answer = definitionFor(
      { status: 'ok', declarations: [FIRST, SECOND] },
      URI,
      index,
    );
    if (answer.kind !== 'locations') throw new Error('expected locations');
    expect(answer.locations).toEqual([
      { uri: URI, range: index.rangeOf(FIRST.region) },
      { uri: URI, range: index.rangeOf(SECOND.region) },
    ]);
  });

  it('keeps the service order and picks no favourite', () => {
    const index = lines();
    const answer = definitionFor(
      { status: 'ok', declarations: [SECOND, FIRST] },
      URI,
      index,
    );
    if (answer.kind !== 'locations') throw new Error('expected locations');
    expect(answer.locations[0]?.range).toEqual(index.rangeOf(SECOND.region));
  });

  it('selects the characters the service selected', () => {
    expect(TEXT.slice(FIRST.region.start, FIRST.region.end)).toBe('Office');
    expect(TEXT.slice(SECOND.region.start, SECOND.region.end)).toBe('Office2');
  });

  it('returns nothing where the name is declared nowhere', () => {
    const answer = definitionFor({ status: 'ok', declarations: [] }, URI, lines());
    if (answer.kind !== 'nothing') throw new Error('expected an absence');
    // The dangling-reference finding is what tells the reader why. A guess here would contradict it.
    expect(answer.absence).toEqual({ kind: 'permitsNothing', reason: 'empty' });
  });

  it('returns nothing where the field points at nothing', () => {
    const answer = definitionFor({ status: 'notApplicable' }, URI, lines());
    expect(answer.kind).toBe('nothing');
    expect(Object.hasOwn(answer, 'locations')).toBe(false);
  });

  it('returns nothing where no schema could be consulted', () => {
    const answer = definitionFor({ status: 'noSchema' }, URI, lines());
    if (answer.kind !== 'nothing') throw new Error('expected an absence');
    expect(answer.absence).toEqual({
      kind: 'cannotAnswer',
      reason: 'noSchema',
      typeName: undefined,
    });
  });
});
