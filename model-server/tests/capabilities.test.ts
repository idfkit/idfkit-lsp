import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterAll, describe, expect, it } from 'vitest';

import {
  DeclarationError,
  capabilityFor,
  loadDeclaration,
  presentRequests,
  serverById,
} from '../src/capabilities.js';

/**
 * The declaration as it sits on disk, before the loader has had an opinion about it. Written out
 * rather than reused from the loader's own types, so a test can build a malformed one: a fixture
 * typed as the loader's result could not express the shapes the loader exists to refuse.
 */
interface RawCapability {
  request: string;
  state: string;
  reason?: string;
  instead?: string;
  tracked?: string;
  editor_specific?: boolean;
}

interface RawDocumentKind {
  language_id: string;
  extensions: string[];
}

interface RawServer {
  id: string;
  runtime: string;
  documents: RawDocumentKind[];
  capabilities: RawCapability[];
}

interface RawDeclaration {
  version: number;
  servers: RawServer[];
}

const fixtureDirectory = mkdtempSync(join(tmpdir(), 'idfkit-lsp-capabilities-'));
let fixtureCount = 0;

afterAll(() => {
  rmSync(fixtureDirectory, { recursive: true, force: true });
});

/**
 * A declaration that breaks no rule, deliberately smaller than the repository's own. The rule tests
 * mutate one field of a fixture that would otherwise load, so a failure names the mutation rather
 * than something the fixture was already carrying.
 */
function wellFormed(): RawDeclaration {
  return {
    version: 1,
    servers: [
      {
        id: 'source',
        runtime: 'a runtime',
        documents: [{ language_id: 'python', extensions: ['.py'] }],
        capabilities: [
          { request: 'textDocument/hover', state: 'present' },
          {
            request: 'textDocument/definition',
            state: 'absent_permanent',
            reason: 'a reason',
            instead: 'the other server',
          },
        ],
      },
      {
        id: 'model',
        runtime: 'another runtime',
        documents: [{ language_id: 'idf', extensions: ['.idf'] }],
        capabilities: [
          { request: 'idfkit-lsp/versions', state: 'present' },
          {
            request: 'textDocument/hover',
            state: 'absent_temporary',
            tracked: 'a tracked item',
          },
        ],
      },
    ],
  };
}

function sourceOf(declaration: RawDeclaration): RawServer {
  const found = declaration.servers.find((server) => server.id === 'source');
  if (found === undefined) throw new Error('the fixture lost its source server');
  return found;
}

function modelOf(declaration: RawDeclaration): RawServer {
  const found = declaration.servers.find((server) => server.id === 'model');
  if (found === undefined) throw new Error('the fixture lost its model server');
  return found;
}

function write(declaration: unknown): string {
  const path = join(fixtureDirectory, `declaration-${(fixtureCount += 1)}.json`);
  writeFileSync(path, JSON.stringify(declaration, null, 2), 'utf-8');
  return path;
}

/** Load a fixture the loader must refuse, and hand back the message it refused with. */
function refusalFor(declaration: unknown): string {
  const path = write(declaration);
  try {
    loadDeclaration(path);
  } catch (error) {
    expect(error).toBeInstanceOf(DeclarationError);
    return (error as Error).message;
  }
  throw new Error('the loader accepted a declaration it was supposed to refuse');
}

describe('a declaration that breaks no rule', () => {
  it('loads, with each state and its supporting text carried through', () => {
    const declaration = loadDeclaration(write(wellFormed()));

    expect(declaration.version).toBe(1);
    expect(declaration.servers.map((server) => server.id)).toEqual(['source', 'model']);

    const model = serverById(declaration, 'model');
    expect(model.documents[0]?.languageId).toBe('idf');
    expect(model.documents[0]?.extensions).toEqual(['.idf']);

    const hover = capabilityFor(model, 'textDocument/hover');
    expect(hover?.state).toBe('absent_temporary');
    expect(hover?.tracked).toBe('a tracked item');
    expect(hover?.reason).toBeUndefined();
    expect(hover?.editorSpecific).toBe(false);
  });

  it('reports which requests are present, which is what the wiring advertises from', () => {
    const declaration = loadDeclaration(write(wellFormed()));

    expect([...presentRequests(serverById(declaration, 'model'))]).toEqual(['idfkit-lsp/versions']);
    expect([...presentRequests(serverById(declaration, 'source'))]).toEqual([
      'textDocument/hover',
    ]);
  });
});

describe('a state that does not say what it must', () => {
  it('refuses absent_permanent with no reason', () => {
    const declaration = wellFormed();
    const capability = sourceOf(declaration).capabilities[1];
    expect(capability).toBeDefined();
    delete capability?.reason;

    const message = refusalFor(declaration);
    expect(message).toContain("server 'source'");
    expect(message).toContain("request 'textDocument/definition'");
    expect(message).toContain("rule 'absent_permanent states a reason' broken");
  });

  it('refuses absent_permanent with no instead', () => {
    const declaration = wellFormed();
    const capability = sourceOf(declaration).capabilities[1];
    expect(capability).toBeDefined();
    delete capability?.instead;

    const message = refusalFor(declaration);
    expect(message).toContain("server 'source'");
    expect(message).toContain("request 'textDocument/definition'");
    expect(message).toContain("rule 'absent_permanent names what to use instead' broken");
  });

  it('refuses absent_temporary with nothing tracked', () => {
    const declaration = wellFormed();
    const capability = modelOf(declaration).capabilities[1];
    expect(capability).toBeDefined();
    delete capability?.tracked;

    const message = refusalFor(declaration);
    expect(message).toContain("server 'model'");
    expect(message).toContain("request 'textDocument/hover'");
    expect(message).toContain("rule 'absent_temporary names the tracked item' broken");
  });

  for (const field of ['reason', 'instead', 'tracked'] as const) {
    it(`refuses present carrying ${field}`, () => {
      const declaration = wellFormed();
      const capability = modelOf(declaration).capabilities[0];
      expect(capability).toBeDefined();
      if (capability !== undefined) capability[field] = 'text a present capability may not carry';

      const message = refusalFor(declaration);
      expect(message).toContain("server 'model'");
      expect(message).toContain("request 'idfkit-lsp/versions'");
      expect(message).toContain("rule 'present carries no reason, instead, or tracked' broken");
      expect(message).toContain(field);
    });
  }

  it('refuses a state outside the three', () => {
    const declaration = wellFormed();
    const capability = modelOf(declaration).capabilities[0];
    expect(capability).toBeDefined();
    if (capability !== undefined) capability.state = 'maybe';

    const message = refusalFor(declaration);
    expect(message).toContain("server 'model'");
    expect(message).toContain("request 'idfkit-lsp/versions'");
    expect(message).toContain("rule 'state is one of");
    expect(message).toContain('maybe');
  });
});

describe('two servers that cannot both be right', () => {
  it('refuses one language id claimed twice', () => {
    const declaration = wellFormed();
    modelOf(declaration).documents = [{ language_id: 'python', extensions: ['.notpy'] }];

    const message = refusalFor(declaration);
    expect(message).toContain("servers 'source' and 'model'");
    expect(message).toContain("rule 'one server per language id' broken");
    expect(message).toContain('python');
  });

  it('refuses one extension claimed twice', () => {
    const declaration = wellFormed();
    modelOf(declaration).documents = [{ language_id: 'idf', extensions: ['.py'] }];

    const message = refusalFor(declaration);
    expect(message).toContain("servers 'source' and 'model'");
    expect(message).toContain("rule 'one server per extension' broken");
    expect(message).toContain('.py');
  });

  it('refuses one request stated twice within a server', () => {
    const declaration = wellFormed();
    modelOf(declaration).capabilities.push({ request: 'idfkit-lsp/versions', state: 'present' });

    const message = refusalFor(declaration);
    expect(message).toContain("server 'model'");
    expect(message).toContain("request 'idfkit-lsp/versions'");
    expect(message).toContain("rule 'a request appears once per server' broken");
  });

  it('refuses fewer than two servers', () => {
    const declaration = wellFormed();
    declaration.servers = [sourceOf(declaration)];

    const message = refusalFor(declaration);
    expect(message).toContain("rule 'two servers are declared, one per document kind' broken");
  });

  it('refuses a server id nobody ships', () => {
    const declaration = wellFormed();
    modelOf(declaration).id = 'schema';

    const message = refusalFor(declaration);
    expect(message).toContain("server 'schema'");
    expect(message).toContain("rule 'a server id is one of");
  });

  it('refuses a declaration missing one of the two ids', () => {
    const declaration = wellFormed();
    const second = modelOf(declaration);
    second.id = 'source';
    second.documents = [{ language_id: 'idf', extensions: ['.idf'] }];

    const message = refusalFor(declaration);
    expect(message).toContain("rule 'each server id is declared once' broken");
    expect(message).toContain('model');
  });
});

describe('a file that is not a declaration at all', () => {
  it('refuses a record that is not a JSON object', () => {
    expect(refusalFor([])).toContain("rule 'is a JSON object' broken");
  });

  it('refuses unreadable JSON', () => {
    const path = join(fixtureDirectory, 'malformed.json');
    writeFileSync(path, '{ not json', 'utf-8');

    expect(() => loadDeclaration(path)).toThrow(DeclarationError);
    expect(() => loadDeclaration(path)).toThrow(/not valid JSON/);
  });

  it('refuses a declaration that is not there', () => {
    const path = join(fixtureDirectory, 'absent.json');

    expect(() => loadDeclaration(path)).toThrow(DeclarationError);
    expect(() => loadDeclaration(path)).toThrow(/cannot be read/);
  });
});

describe('the declaration this repository actually ships', () => {
  const declaration = loadDeclaration();
  const model = serverById(declaration, 'model');
  const source = serverById(declaration, 'source');

  it('loads from the repository root without being told where it is', () => {
    expect(declaration.servers).toHaveLength(2);
  });

  it('has the model server serving model text and the source server serving source', () => {
    expect(model.documents.map((kind) => kind.languageId)).toEqual(['idf']);
    expect(model.documents.flatMap((kind) => [...kind.extensions])).toEqual(['.idf']);
    expect(source.documents.map((kind) => kind.languageId)).toEqual(['python']);
  });

  it('claims document kinds disjoint from the source server', () => {
    const modelLanguages = new Set(model.documents.map((kind) => kind.languageId));
    const modelExtensions = new Set(model.documents.flatMap((kind) => [...kind.extensions]));
    for (const kind of source.documents) {
      expect(modelLanguages.has(kind.languageId)).toBe(false);
      for (const extension of kind.extensions) {
        expect(modelExtensions.has(extension)).toBe(false);
      }
    }
  });

  it('advertises the version request, which needs nothing that is not published', () => {
    expect(capabilityFor(model, 'idfkit-lsp/versions')?.state).toBe('present');
    expect([...presentRequests(model)]).toContain('idfkit-lsp/versions');
  });

  // The five answers about model text wait on the same unpublished component, so each states what
  // closes it rather than being advertised and then declined at request time (Principle IV).
  for (const request of [
    'textDocument/semanticTokens/full',
    'textDocument/diagnostic',
    'textDocument/completion',
    'textDocument/hover',
    'textDocument/definition',
  ]) {
    it(`states ${request} as temporarily absent, tracking the language service`, () => {
      const capability = capabilityFor(model, request);
      expect(capability?.state).toBe('absent_temporary');
      expect(capability?.tracked).toContain('@idfkit/language');
      expect(capability?.reason).toBeUndefined();
      expect(capability?.instead).toBeUndefined();
    });
  }

  it('tracks the push fallback on the same component as the diagnostic request', () => {
    const capability = capabilityFor(model, 'textDocument/publishDiagnostics');
    expect(capability?.state).toBe('absent_temporary');
    expect(capability?.tracked).toContain('@idfkit/language');
  });

  it('states signature help as permanently absent, with a reason and somewhere else to look', () => {
    const capability = capabilityFor(model, 'textDocument/signatureHelp');
    expect(capability?.state).toBe('absent_permanent');
    expect(capability?.reason).toBeTruthy();
    expect(capability?.instead).toBeTruthy();
    expect(capability?.tracked).toBeUndefined();
  });

  it('advertises nothing it cannot answer today', () => {
    expect([...presentRequests(model)]).toEqual(['idfkit-lsp/versions']);
  });
});
