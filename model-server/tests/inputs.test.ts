/**
 * The four inputs the language service takes but does not produce.
 *
 * Every test here injects the library rather than resolving the installed one. The point is the
 * resolution rules, and a suite that read `node_modules` would pass or fail on whether someone has
 * linked a local build that day. The one thing that is asserted about the real library is nothing:
 * this file never imports it.
 */

import { describe, expect, it, vi } from 'vitest';

import {
  CORE_FALLBACK,
  CORE_NOT_INSTALLED,
  CORE_SUBPATH,
  NODE_FALLBACK,
  NODE_SUBPATH,
  loadInputs,
} from '../src/inputs.js';

import type { ClassifiedRegion } from '../src/language-service.js';

/** A version the fake bundle can serve, and the text that declares it. */
const SERVED = '9.4.0';
const UNSERVED = '1.0.0';

interface FakeOptions {
  /** What `getIdfVersion` reports. Undefined stands for text with no determinable version. */
  readonly version?: string | undefined;
  /** Whether reading the prose pool fails, standing for a bundle that ships no prose. */
  readonly proseThrows?: boolean;
  /** Whether parsing throws, standing for text too broken for even a lenient read. */
  readonly parseThrows?: boolean;
  readonly tokens?: readonly ClassifiedRegion[];
}

/**
 * The library, in the members `inputs.ts` calls and no others.
 *
 * `load` resolves only for the one version the fake serves, so the difference between a version
 * that is not loaded yet and one that can never be loaded is observable.
 */
function fakeLibrary(options: FakeOptions = {}) {
  const loaded = new Map<string, object>();
  const parseIdf = vi.fn((_text: string, _schema: object, parseOptions?: { strict?: boolean }) => {
    if (options.parseThrows === true) throw new Error('unterminated');
    return { document: { parsedWith: parseOptions } };
  });
  const core = {
    getIdfVersion: () => ('version' in options ? options.version : SERVED),
    scanIdf: (text: string) => ({ text }),
    classify: () => options.tokens ?? [{ start: 0, end: 3, kind: 'typeName' }],
    parseIdf,
  };
  let pool: readonly string[] | undefined;
  const bundle = {
    loadProse: vi.fn(async () => {
      if (options.proseThrows === true) throw new Error('no prose in this bundle');
      pool = ['the first sentence', 'the second'];
      return pool;
    }),
    prose: () => pool,
    load: vi.fn(async (version: string) => {
      if (version !== SERVED) throw new Error(`no such version ${version}`);
      const schema = { version };
      loaded.set(version, schema);
      return schema;
    }),
    loaded: (version: string) => loaded.get(version),
    latest: async () => SERVED,
  };
  const node = { schemas: () => bundle };

  const asked: string[] = [];
  /** Resolves whichever names the fake was told to serve, and records every specifier tried. */
  const serving = (served: readonly string[]) => (specifier: string): Promise<unknown> => {
    asked.push(specifier);
    if (!served.includes(specifier)) {
      const error = new Error(`Cannot find package '${specifier}'`);
      Object.assign(error, { code: 'ERR_MODULE_NOT_FOUND' });
      return Promise.reject(error);
    }
    if (specifier === CORE_SUBPATH || specifier === CORE_FALLBACK) return Promise.resolve(core);
    return Promise.resolve(node);
  };

  const load = serving([CORE_SUBPATH, NODE_SUBPATH]);

  return { load, serving, asked, bundle, parseIdf };
}

/** Resolved inputs, or a failure the caller of this helper was not expecting. */
async function resolved(options: FakeOptions = {}) {
  const library = fakeLibrary(options);
  const result = await loadInputs(() => {}, library.load);
  if (!result.ok) throw new Error(`expected inputs, got: ${result.message}`);
  return { ...result, ...library };
}

describe('when the library is not installed', () => {
  it('reports rather than throws, and names what to install', async () => {
    const result = await loadInputs(
      () => {},
      () => Promise.reject(new Error("Cannot find package 'idfkit'")),
    );

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.message).toContain('npm install');
    expect(result.message).toContain(CORE_SUBPATH);
  });

  it("carries the resolver's own words as well as its own", async () => {
    const result = await loadInputs(
      () => {},
      () => Promise.reject(new Error('a specific resolver complaint')),
    );

    if (result.ok) throw new Error('unreachable');
    expect(result.message).toContain(CORE_NOT_INSTALLED);
    expect(result.message).toContain('a specific resolver complaint');
  });
});

describe('resolving a schema', () => {
  it('answers with none the first time a version is named, rather than blocking', async () => {
    const { inputs } = await resolved();
    expect(inputs.schemaFor('any text')).toBeUndefined();
  });

  it('answers with the schema once the load this server awaited has finished', async () => {
    const { inputs, warm } = await resolved();
    await warm('any text');
    expect(inputs.schemaFor('any text')).toBeDefined();
  });

  it('tells the caller when a schema arrives, so answers can be offered again', async () => {
    const arrived = vi.fn();
    const library = fakeLibrary();
    const result = await loadInputs(arrived, library.load);
    if (!result.ok) throw new Error('unreachable');

    result.inputs.schemaFor('any text');
    await vi.waitFor(() => expect(arrived).toHaveBeenCalledWith(SERVED));
  });

  it('starts one load per version however many times it is asked', async () => {
    const { inputs, bundle } = await resolved();
    inputs.schemaFor('any text');
    inputs.schemaFor('any text');
    inputs.schemaFor('any text');
    expect(bundle.load).toHaveBeenCalledTimes(1);
  });

  it('resolves none for text whose version cannot be determined, and asks for none', async () => {
    const { inputs, bundle } = await resolved({ version: undefined });
    expect(inputs.schemaFor('text with no version statement')).toBeUndefined();
    expect(bundle.load).not.toHaveBeenCalled();
  });

  it('keeps saying none for a version the bundle cannot serve, without rejecting', async () => {
    const { inputs, warm } = await resolved({ version: UNSERVED });
    await expect(warm('any text')).resolves.toBeUndefined();
    expect(inputs.schemaFor('any text')).toBeUndefined();
  });
});

describe('classifying', () => {
  it("passes the syntax layer's regions through without touching them", async () => {
    const tokens: readonly ClassifiedRegion[] = [
      { start: 0, end: 8, kind: 'typeName' },
      { start: 8, end: 9, kind: 'separator' },
    ];
    const { inputs } = await resolved({ tokens });
    expect(inputs.classify('Version,')).toEqual(tokens);
  });
});

describe('reading the model behind the text', () => {
  it('parses leniently, so a statement still being typed does not lose the ones above it', async () => {
    const { inputs, warm, parseIdf } = await resolved();
    await warm('any text');

    inputs.documentFor('any text');
    expect(parseIdf).toHaveBeenCalledWith('any text', expect.anything(), { strict: false });
  });

  it('reads no model when no schema has been resolved', async () => {
    const { inputs, parseIdf } = await resolved();
    expect(inputs.documentFor('any text')).toBeUndefined();
    expect(parseIdf).not.toHaveBeenCalled();
  });

  it('reads no model from text too broken for even a lenient parse', async () => {
    const { inputs, warm } = await resolved({ parseThrows: true });
    await warm('any text');
    expect(inputs.documentFor('any text')).toBeUndefined();
  });
});

describe('prose', () => {
  it('supplies none before anything has been loaded', async () => {
    const { inputs } = await resolved();
    expect(inputs.proseFor('any text')).toBeUndefined();
  });

  it('supplies the pool the bundle loaded once a document has arrived', async () => {
    const { inputs, warm } = await resolved();
    await warm('any text');
    expect(inputs.proseFor('any text')).toEqual(['the first sentence', 'the second']);
  });

  it('asks for the pool once however many documents arrive', async () => {
    const { warm, bundle } = await resolved();
    await warm('any text');
    await warm('another text');
    await warm('a third text');
    expect(bundle.loadProse).toHaveBeenCalledTimes(1);
  });

  it('leaves prose absent when the bundle carries none, and resolves the schema anyway', async () => {
    const { inputs, warm } = await resolved({ proseThrows: true });
    await expect(warm('any text')).resolves.toBeUndefined();
    expect(inputs.proseFor('any text')).toBeUndefined();
    // The failure that belongs to prose does not take the schema down with it.
    expect(inputs.schemaFor('any text')).toBeDefined();
  });
});

describe('which specifiers the inputs are resolved through', () => {
  it('asks for the shared name first and stops there when it resolves', async () => {
    const library = fakeLibrary();
    const result = await loadInputs(() => {}, library.serving([CORE_SUBPATH, NODE_SUBPATH]));

    expect(result.ok).toBe(true);
    expect(library.asked).toEqual([CORE_SUBPATH, NODE_SUBPATH]);
  });

  it("falls back to the component's own name where the shared name resolves to nothing", async () => {
    const library = fakeLibrary();
    const result = await loadInputs(() => {}, library.serving([CORE_FALLBACK, NODE_FALLBACK]));

    expect(result.ok).toBe(true);
    expect(library.asked).toEqual([CORE_SUBPATH, CORE_FALLBACK, NODE_SUBPATH, NODE_FALLBACK]);
  });

  it('reports the shared name as what to install when neither resolves', async () => {
    const library = fakeLibrary();
    const result = await loadInputs(() => {}, library.serving([]));

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.message).toContain(CORE_NOT_INSTALLED);
  });
});
