/**
 * The language service boundary with the component absent (T030), and the
 * document store that feeds it (T034).
 *
 * `@idfkit/language` ships now and this repository installs it, so the absent
 * path is no longer what runs here. Every test below injects the failure it is
 * about, which is what the quickstart's scenario 7 requires: the path where the
 * component is missing must be tested whether or not it is installed. What they
 * pin is the behaviour `contracts/model-server.md` point 8 requires, that the
 * component's absence is a message and not a crash, and the rule that the
 * message is the guard's own words wherever a guard spoke.
 */

import { describe, expect, it, vi } from 'vitest';

import {
  completionOutcome,
  declarationOutcome,
  explanationOutcome,
  isAnswer,
} from '../src/absence.js';
import { ModelDocuments } from '../src/documents.js';
import {
  COMPONENT,
  SHARED_NAME,
  SPECIFIER_ORDER,
  loadLanguageService,
  NOT_INSTALLED,
  SUBPATH,
} from '../src/service.js';

import type { ServiceHandle } from '../src/documents.js';
import type { CompletionResult } from '../src/language-service.js';
import type { TextDocumentContentChangeEvent } from 'vscode-languageserver-textdocument';

/**
 * The facade's guard, word for word in shape, with the component substituted.
 *
 * Copied from the pattern `@idfkit/idfkit/weather` already ships rather than invented,
 * because the point of the assertion below is that this text survives the trip
 * unedited. If it were this repository's wording the test would prove nothing.
 */
const GUARD_MESSAGE =
  `${SUBPATH} requires the optional component '${COMPONENT}', which is not installed.\n` +
  '\n' +
  `    npm install ${COMPONENT}\n` +
  '\n' +
  `It is an optional peer dependency, so installing ${SHARED_NAME} deliberately leaves it out: the ` +
  'language service stays off disk for everyone who does not ask for it. Everything else in ' +
  `${SHARED_NAME} works without it.`;

/** A stand-in carrying the six functions the contract fixes, and nothing real. */
function stubService(): Record<string, unknown> {
  return {
    contextAt: () => undefined,
    completionsAt: () => undefined,
    explainAt: () => undefined,
    declarationAt: () => undefined,
    findingsIn: () => [],
    position: () => [],
  };
}

/** Node's own shape for a specifier that resolved to nothing. */
function resolverError(specifier: string): Error {
  const error = new Error(
    `Cannot find package '${specifier}' imported from /somewhere/model-server/src/service.js`,
  );
  Object.assign(error, { code: 'ERR_MODULE_NOT_FOUND' });
  return error;
}

describe('loadLanguageService with the component absent', () => {
  it('reports rather than throws, and names what to install', async () => {
    // The failure is injected rather than borrowed from this checkout. Scenario 7 requires this
    // to pass whether or not the component is installed, because it is about the path where it
    // is not: a fresh clone and CI have it absent, and a local link of an unpublished build has
    // it present. Reading the real subpath here would make the test an accident of node_modules.
    const result = await loadLanguageService(() => Promise.reject(resolverError(SUBPATH)));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.message).toContain('npm install');
    expect(result.message).toContain(COMPONENT);
    expect(result.message).toContain(SUBPATH);
  });

  it('does not reject, so startup has something to report', async () => {
    await expect(
      loadLanguageService(() => Promise.reject(resolverError(SUBPATH))),
    ).resolves.toBeDefined();
  });

  it("passes the guard's message through unchanged", async () => {
    const result = await loadLanguageService(() => Promise.reject(new Error(GUARD_MESSAGE)));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.origin).toBe('guard');
    // The whole assertion: byte for byte the guard's, not reworded and not
    // replaced by this repository's own.
    expect(result.message).toBe(GUARD_MESSAGE);
    expect(result.message).not.toBe(NOT_INSTALLED);
  });

  it('speaks for itself only when nothing was installed to speak', async () => {
    const result = await loadLanguageService(() => Promise.reject(resolverError(SHARED_NAME)));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.origin).toBe('resolver');
    expect(result.message).toBe(NOT_INSTALLED);
    // The component's own name, not the shared name. This is the one place this repository does
    // not send a user to the shared name, because the shared name is not on npm and an
    // instruction that reads better but fails is worse than one that works.
    expect(result.message).toContain(`npm install ${COMPONENT}`);
    expect(result.message).toContain(SHARED_NAME);
  });

  it('treats an unresolvable subpath the same way', async () => {
    const result = await loadLanguageService(() => Promise.reject(resolverError(SUBPATH)));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.origin).toBe('resolver');
  });

  it('rethrows a failure that is not the component missing', async () => {
    // Thrown from inside a component that is installed. Telling someone to
    // install what they already have would be worse than the original message.
    const inside = new TypeError('cannot read properties of undefined (reading "fields")');

    await expect(loadLanguageService(() => Promise.reject(inside))).rejects.toBe(inside);
  });

  it('rethrows a resolution failure naming some third package', async () => {
    const third = resolverError('@idfkit/core');

    await expect(loadLanguageService(() => Promise.reject(third))).rejects.toBe(third);
  });

  it('reports a resolved module that does not carry the surface', async () => {
    const result = await loadLanguageService(() => Promise.resolve({ contextAt: () => undefined }));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.message).toContain('completionsAt');
  });

  it('hands back the service when the surface is there', async () => {
    const result = await loadLanguageService(() => Promise.resolve(stubService()));

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.message);
    expect(typeof result.service.completionsAt).toBe('function');
  });
});

describe('ModelDocuments', () => {
  const URI = 'file:///models/office.idf';

  function edit(text: string, line: number, from: number, to: number): TextDocumentContentChangeEvent {
    return {
      range: { start: { line, character: from }, end: { line, character: to } },
      text,
    };
  }

  it('holds a document from open, with the negotiated encoding', () => {
    const documents = new ModelDocuments();
    documents.negotiate('utf-8');

    const opened = documents.open(URI, 'idf', 1, 'Zone,\n  Office;\n');

    expect(opened.uri).toBe(URI);
    expect(opened.version).toBe(1);
    expect(opened.encoding).toBe('utf-8');
    expect(opened.handle).toBeUndefined();
    expect(documents.uris).toEqual([URI]);
  });

  it('applies an incremental change and moves the version with it', () => {
    const documents = new ModelDocuments();
    documents.open(URI, 'idf', 1, 'Zone,\n  Office;\n');

    const updated = documents.update(URI, [edit('Lobby', 1, 2, 8)], 2);

    expect(updated?.version).toBe(2);
    expect(updated?.text).toBe('Zone,\n  Lobby;\n');
    expect(documents.textOf(URI)).toBe('Zone,\n  Lobby;\n');
    expect(documents.versionOf(URI)).toBe(2);
  });

  it('marks an answer computed against a superseded version', () => {
    const documents = new ModelDocuments();
    documents.open(URI, 'idf', 1, 'Zone,\n  Office;\n');

    expect(documents.isSuperseded(URI, 1)).toBe(false);

    documents.update(URI, [edit('Lobby', 1, 2, 8)], 2);

    expect(documents.isSuperseded(URI, 1)).toBe(true);
    expect(documents.isSuperseded(URI, 2)).toBe(false);
  });

  it('yields nothing at all for a URI it never held', () => {
    const documents = new ModelDocuments();

    expect(documents.get(URI)).toBeUndefined();
    expect(documents.textOf(URI)).toBeUndefined();
    expect(documents.versionOf(URI)).toBeUndefined();
    expect(documents.update(URI, [edit('x', 0, 0, 0)], 2)).toBeUndefined();
    expect(documents.attach(URI, { applyChanges: () => undefined })).toBe(false);
    // An answer about a document this server does not hold is dropped, not guessed.
    expect(documents.isSuperseded(URI, 1)).toBe(true);
  });

  it('forgets a closed document rather than answering from what it remembers', () => {
    const documents = new ModelDocuments();
    documents.open(URI, 'idf', 1, 'Zone,\n  Office;\n');
    documents.close(URI);

    expect(documents.get(URI)).toBeUndefined();
    expect(documents.textOf(URI)).toBeUndefined();
    expect(documents.uris).toEqual([]);
    expect(documents.isSuperseded(URI, 1)).toBe(true);
  });

  it('feeds a handle the same changes, once one is attached', () => {
    // The preferred half of the branch, exercised with a stand-in because the
    // service that would supply a real handle does not exist yet.
    const documents = new ModelDocuments();
    documents.open(URI, 'idf', 1, 'Zone,\n  Office;\n');

    const applyChanges = vi.fn();
    const handle: ServiceHandle = { applyChanges };
    expect(documents.attach(URI, handle)).toBe(true);

    const changes = [edit('Lobby', 1, 2, 8)];
    const updated = documents.update(URI, changes, 2);

    expect(applyChanges).toHaveBeenCalledWith(changes, 2);
    expect(updated?.handle).toBe(handle);
    // The store keeps the text either way, so the fallback stays available.
    expect(updated?.text).toBe('Zone,\n  Lobby;\n');
  });
});

describe('the three absences, kept three', () => {
  // absence.ts is what stops a handler flattening these into one empty result,
  // so the mapping is asserted here rather than left to the handlers that use
  // it. Everything below is a service result shape, translated and nothing else.

  it('tells a schema that permits nothing from one that constrains nothing', () => {
    expect(completionOutcome({ status: 'ok', offers: [] })).toEqual({
      kind: 'permitsNothing',
      reason: 'empty',
    });
    expect(completionOutcome({ status: 'unconstrained' })).toEqual({ kind: 'constrainsNothing' });
  });

  it('never reports a missing schema as an empty answer', () => {
    expect(completionOutcome({ status: 'noSchema' })).toEqual({
      kind: 'cannotAnswer',
      reason: 'noSchema',
      typeName: undefined,
    });
    expect(completionOutcome({ status: 'unknownType', typeName: 'Zne' })).toEqual({
      kind: 'cannotAnswer',
      reason: 'unknownType',
      typeName: 'Zne',
    });
  });

  it('carries an answer through untouched', () => {
    const offers = [
      {
        value: 'Zone',
        replaces: { start: 0, end: 3 },
        kind: 'objectType',
        required: undefined,
        prose: undefined,
      },
    ] as const;
    const outcome = completionOutcome({ status: 'ok', offers });

    expect(isAnswer(outcome)).toBe(true);
    if (!isAnswer(outcome)) throw new Error('unreachable');
    expect(outcome.value).toBe(offers);
  });

  it('answers a status it has never seen with ignorance, not with emptiness', () => {
    // A future release adding a sixth status must not arrive as "nothing here".
    const future = { status: 'somethingNew' } as unknown as CompletionResult;

    expect(completionOutcome(future)).toEqual({
      kind: 'cannotAnswer',
      reason: 'unrecognisedStatus',
      typeName: undefined,
    });
  });

  it('maps the other two answers the same way', () => {
    expect(explanationOutcome({ status: 'notApplicable' })).toEqual({
      kind: 'permitsNothing',
      reason: 'notApplicable',
    });
    expect(declarationOutcome({ status: 'ok', declarations: [] })).toEqual({
      kind: 'permitsNothing',
      reason: 'empty',
    });
    expect(declarationOutcome({ status: 'noSchema' })).toEqual({
      kind: 'cannotAnswer',
      reason: 'noSchema',
      typeName: undefined,
    });
  });
});

describe('which specifier the service is reached through', () => {
  it('prefers the shared name, which is the one a user should install', () => {
    expect(SPECIFIER_ORDER[0]).toBe(SUBPATH);
  });

  it('accepts the component under its own name after it', () => {
    expect(SPECIFIER_ORDER).toEqual([SUBPATH, COMPONENT]);
  });

  it('asks for the shared name first and stops there when it resolves', async () => {
    const asked: string[] = [];
    const result = await loadLanguageService((specifier) => {
      asked.push(specifier);
      return Promise.resolve(stubService());
    });

    expect(result.ok).toBe(true);
    expect(asked).toEqual([SUBPATH]);
  });

  it('falls back to the component when the shared name resolves to nothing', async () => {
    const asked: string[] = [];
    const result = await loadLanguageService((specifier) => {
      asked.push(specifier);
      if (specifier === SUBPATH) return Promise.reject(resolverError(SUBPATH));
      return Promise.resolve(stubService());
    });

    expect(result.ok).toBe(true);
    expect(asked).toEqual([SUBPATH, COMPONENT]);
  });

  it('reports the shared name as what to install when neither resolves', async () => {
    const result = await loadLanguageService((specifier) =>
      Promise.reject(resolverError(specifier)),
    );

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    // The fallback exists so this server can answer, not so a user learns to install the
    // component directly. What to install is still the shared name.
    expect(result.message).toBe(NOT_INSTALLED);
  });

  it("does not try the component after the facade's guard has already spoken", async () => {
    const asked: string[] = [];
    const guard = new Error(`${SUBPATH} requires the optional component '${COMPONENT}'`);
    const result = await loadLanguageService((specifier) => {
      asked.push(specifier);
      return Promise.reject(guard);
    });

    if (result.ok) throw new Error('unreachable');
    // The guard running means the shared name is installed and the component is not. Asking for
    // the component next would fail again, in worse words than the guard's own.
    expect(result.origin).toBe('guard');
    expect(asked).toEqual([SUBPATH]);
  });
});
