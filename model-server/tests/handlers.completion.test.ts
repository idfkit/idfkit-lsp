/**
 * What the schema permits at an offset, translated (T044, T048).
 *
 * Three claims are worth the test file on their own. That "the schema constrains nothing here"
 * reaches the client as an empty list marked complete, so an editor stops asking. That "no schema
 * could be consulted" does not reach the client as a list at all, because an empty list there says
 * the schema permits nothing, which is a different claim and a false one. And that there is no
 * local list of candidates anywhere in the module, which is the only way "we never fall back to a
 * guess" can be checked rather than promised.
 *
 * Every result here is a hand-written stand-in for `@idfkit/language`, which is not published. The
 * handler is a pure translation, so a fake result exercises all of it.
 */

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { completionFor } from '../src/handlers/completion.js';
import { LineIndex } from '../src/positions.js';

import type { CompletionResult, Offer } from '../src/language-service.js';
import type { TextEdit } from 'vscode-languageserver';

/**
 * A type name containing a colon and a value containing spaces: the two shapes an editor's default
 * word rules get wrong in opposite directions, which is why FR-048 puts the replaced span on the
 * offer and why this file uses it rather than measuring anything.
 */
const TEXT = 'BuildingSurface:Detailed,\n  Office Zone 1,\n';
const lines = () => new LineIndex(TEXT, 'utf-16');

const TYPE_NAME = { start: 0, end: 24 };
const REFERENCE_VALUE = { start: 28, end: 41 };

const OFFERS: readonly Offer[] = [
  {
    value: 'BuildingSurface:Detailed',
    replaces: TYPE_NAME,
    kind: 'objectType',
    required: undefined,
    prose: 'the schema says this, and the handler repeats it',
  },
  {
    value: 'FenestrationSurface:Detailed',
    replaces: TYPE_NAME,
    kind: 'objectType',
    required: undefined,
    prose: undefined,
  },
];

const REFERENCE_OFFERS: readonly Offer[] = [
  {
    value: 'Office Zone 1',
    replaces: REFERENCE_VALUE,
    kind: 'referenceTarget',
    required: true,
    prose: undefined,
  },
];

describe('the schema constrains nothing here', () => {
  const answer = completionFor({ status: 'unconstrained' }, lines());

  it('returns a list, and the list is empty', () => {
    expect(answer.kind).toBe('list');
    if (answer.kind !== 'list') return;
    expect(answer.list.items).toEqual([]);
  });

  it('marks the empty list complete, so the editor stops asking', () => {
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list.isIncomplete).toBe(false);
  });

  it('says which of the two schema answers the empty list stands for', () => {
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.absence).toEqual({ kind: 'constrainsNothing' });
  });
});

describe('the schema permits nothing here', () => {
  const answer = completionFor({ status: 'ok', offers: [] }, lines());

  it('is also an empty complete list, and is not the same absence', () => {
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list).toEqual({ isIncomplete: false, items: [] });
    expect(answer.absence).toEqual({ kind: 'permitsNothing', reason: 'empty' });
  });

  it('stays distinguishable from constraining nothing, which FR-021 requires', () => {
    const unconstrained = completionFor({ status: 'unconstrained' }, lines());
    if (answer.kind !== 'list' || unconstrained.kind !== 'list') throw new Error('expected lists');
    expect(answer.absence).not.toEqual(unconstrained.absence);
  });
});

describe('no schema could be consulted', () => {
  it('does not return an empty list, and does not return a list at all', () => {
    const answer = completionFor({ status: 'noSchema' }, lines());
    expect(answer.kind).toBe('cannotAnswer');
    expect(Object.hasOwn(answer, 'list')).toBe(false);
  });

  it('carries the reason, so the wiring can say why rather than showing nothing', () => {
    const answer = completionFor({ status: 'noSchema' }, lines());
    if (answer.kind !== 'cannotAnswer') throw new Error('expected an absence');
    expect(answer.absence).toEqual({
      kind: 'cannotAnswer',
      reason: 'noSchema',
      typeName: undefined,
    });
  });

  it('names the type the text wrote when the schema does not define it', () => {
    const answer = completionFor({ status: 'unknownType', typeName: 'Zne' }, lines());
    if (answer.kind !== 'cannotAnswer') throw new Error('expected an absence');
    expect(answer.absence.reason).toBe('unknownType');
    expect(answer.absence.typeName).toBe('Zne');
  });

  it('treats a position where the question does not arise as permitting nothing', () => {
    // Inside a comment the schema was consulted and had nothing to say, which is not the same as
    // never having been consulted, so this one is a list.
    const answer = completionFor({ status: 'notApplicable' }, lines());
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list.items).toEqual([]);
    expect(answer.absence).toEqual({ kind: 'permitsNothing', reason: 'notApplicable' });
  });
});

describe('every item came from an offer', () => {
  const ok: CompletionResult = { status: 'ok', offers: OFFERS };

  it('labels items with the offers own values, in the offers own order', () => {
    const answer = completionFor(ok, lines());
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list.items.map((item) => item.label)).toEqual(OFFERS.map((one) => one.value));
  });

  it('emits exactly one item per offer, for every length of input', () => {
    const index = lines();
    for (let count = 0; count <= 8; count = count + 1) {
      const offers: Offer[] = [];
      for (let made = 0; made < count; made = made + 1) {
        offers.push({ ...(OFFERS[0] as Offer), value: `offer ${made}` });
      }
      const answer = completionFor({ status: 'ok', offers }, index);
      if (answer.kind !== 'list') throw new Error('expected a list');
      expect(answer.list.items.length).toBe(count);
    }
  });

  it('carries the schema prose only where the service supplied it', () => {
    const answer = completionFor(ok, lines());
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list.items[0]?.documentation).toEqual({
      kind: 'plaintext',
      value: OFFERS[0]?.prose,
    });
    expect(Object.hasOwn(answer.list.items[1] ?? {}, 'documentation')).toBe(false);
  });

  it('shows required only where the schema marked the field required', () => {
    const answer = completionFor(ok, lines());
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(Object.hasOwn(answer.list.items[0] ?? {}, 'detail')).toBe(false);

    const marked = completionFor({ status: 'ok', offers: REFERENCE_OFFERS }, lines());
    if (marked.kind !== 'list') throw new Error('expected a list');
    expect(marked.list.items[0]?.detail).toBe('required');
  });
});

describe('the replaced span is the offer own, never a word measured here', () => {
  it('replaces a type name containing a colon, whole', () => {
    const index = lines();
    const answer = completionFor({ status: 'ok', offers: OFFERS }, index);
    if (answer.kind !== 'list') throw new Error('expected a list');
    const edit = answer.list.items[0]?.textEdit;
    expect(edit).toEqual({
      range: index.rangeOf(TYPE_NAME),
      newText: 'BuildingSurface:Detailed',
    });
    expect(TEXT.slice(TYPE_NAME.start, TYPE_NAME.end)).toBe('BuildingSurface:Detailed');
  });

  it('replaces a value containing spaces, whole', () => {
    const index = lines();
    const answer = completionFor({ status: 'ok', offers: REFERENCE_OFFERS }, index);
    if (answer.kind !== 'list') throw new Error('expected a list');
    expect(answer.list.items[0]?.textEdit).toEqual({
      range: index.rangeOf(REFERENCE_VALUE),
      newText: 'Office Zone 1',
    });
    expect(TEXT.slice(REFERENCE_VALUE.start, REFERENCE_VALUE.end)).toBe('Office Zone 1');
  });

  it('selects the same characters whatever unit the client negotiated', () => {
    const astral = 'Zone,Caf\u{1F3E2} A,\n';
    const replaces = { start: 5, end: 12 };
    const offer: Offer = {
      value: 'x',
      replaces,
      kind: 'enumValue',
      required: false,
      prose: undefined,
    };
    for (const encoding of ['utf-8', 'utf-16', 'utf-32'] as const) {
      const index = new LineIndex(astral, encoding);
      const answer = completionFor({ status: 'ok', offers: [offer] }, index);
      if (answer.kind !== 'list') throw new Error('expected a list');
      const edit = answer.list.items[0]?.textEdit as TextEdit | undefined;
      const range = edit?.range;
      expect(index.offsetAt(range?.start ?? { line: 0, character: 0 })).toBe(replaces.start);
      expect(index.offsetAt(range?.end ?? { line: 0, character: 0 })).toBe(replaces.end);
    }
  });
});

describe('there is no local list to fall back to', () => {
  const source = readFileSync(new URL('../src/handlers/completion.ts', import.meta.url), 'utf8');
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

  it('holds no array literal containing a string, anywhere in the module', () => {
    // The check a reviewer would do by eye, done mechanically. A fallback list has to be written
    // down somewhere, and an array of strings is the only shape it can take.
    const literals = code.match(/\[[^\]]*\]/g) ?? [];
    expect(literals.filter((one) => /['"`]/.test(one))).toEqual([]);
  });

  it('produces no item at all when the service produced no offer', () => {
    for (const result of [
      { status: 'ok', offers: [] },
      { status: 'unconstrained' },
      { status: 'notApplicable' },
    ] satisfies CompletionResult[]) {
      const answer = completionFor(result, lines());
      if (answer.kind !== 'list') throw new Error('expected a list');
      expect(answer.list.items).toEqual([]);
    }
  });
});
