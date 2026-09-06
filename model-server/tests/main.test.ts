/**
 * What the wiring can be held to without a client on the other end of a pipe.
 *
 * The protocol suite drives this server as a process, which is where a request in and a response
 * out are proved (Principle VI). What is left for a unit test is the reasoning the wiring does
 * before it ever speaks: which requests it will advertise, which documents it will answer about,
 * what it says its levels are, and which answers it throws away because the editor has moved on.
 *
 * Nothing here spells out a capability, an extension, or a level. Every expectation is read from
 * the same files the server reads, because a test carrying its own copy of the answer would pass
 * on the day it was written and go on passing after the declaration changed.
 */

import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  ErrorCodes,
  LSPErrorCodes,
  ResponseError,
  SignatureHelpRequest,
} from 'vscode-languageserver';
import { describe, expect, it } from 'vitest';

import { loadDeclaration, presentRequests, serverById } from '../src/capabilities.js';
import { ModelDocuments } from '../src/documents.js';
import {
  VERSIONS_REQUEST,
  currentOrDropped,
  loadServiceForStartup,
  planAdvertisement,
  serves,
  unsupported,
  versionReport,
} from '../src/main.js';
import { NOT_INSTALLED } from '../src/service.js';

import type { Capability, CapabilityState, ServerDeclaration } from '../src/capabilities.js';

const declaration = loadDeclaration();
const model = serverById(declaration, 'model');
const source = serverById(declaration, 'source');

/** The manifest the server reports its own level from, read here the same way and separately. */
interface Manifest {
  version?: string;
  dependencies?: Record<string, string>;
  peerDependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
}

function read(url: URL): Manifest | undefined {
  const path = fileURLToPath(url);
  if (!existsSync(path)) return undefined;
  return JSON.parse(readFileSync(path, 'utf-8')) as Manifest;
}

const manifest = read(new URL('../package.json', import.meta.url)) ?? {};

function installedLevel(name: string): string | undefined {
  return read(new URL(`../node_modules/${name}/package.json`, import.meta.url))?.version;
}

/** A capability as the loader hands one over, so a fixture can state one field and mean it. */
function capability(
  request: string,
  state: CapabilityState,
  carried: Partial<Capability> = {},
): Capability {
  return {
    request,
    state,
    reason: undefined,
    instead: undefined,
    tracked: undefined,
    editorSpecific: false,
    ...carried,
  };
}

/** The model server as declared, with its capability list replaced by the one under test. */
function declaring(...capabilities: readonly Capability[]): ServerDeclaration {
  return { ...model, capabilities };
}

/** A URI of the kind a server declares it serves, built from that server's own declaration. */
function uriServedBy(server: ServerDeclaration): string {
  const extension = server.documents[0]?.extensions[0];
  if (extension === undefined) throw new Error(`${server.id} declares no extension`);
  return `file:///somewhere/a-document${extension}`;
}

describe('what the declaration advertises', () => {
  it('advertises exactly what the declaration marks present', () => {
    const plan = planAdvertisement(model, { serviceAvailable: true });
    expect(plan.registered).toEqual([...presentRequests(model)].sort());
  });

  it('advertises nothing the declaration does not mark present', () => {
    const plan = planAdvertisement(model, { serviceAvailable: true });
    for (const skipped of plan.skipped) {
      expect(presentRequests(model).has(skipped.request)).toBe(false);
      expect(skipped.why.length).toBeGreaterThan(0);
    }
  });

  it('carries the reason the declaration gives for each absence', () => {
    const plan = planAdvertisement(model, { serviceAvailable: true });
    for (const skipped of plan.skipped) {
      const declared = model.capabilities.find((entry) => entry.request === skipped.request);
      const stated = declared?.tracked ?? declared?.reason;
      if (stated !== undefined) expect(skipped.why).toContain(stated);
    }
  });

  it('puts a provider in the initialize result for a request marked present', () => {
    const present = planAdvertisement(declaring(capability('textDocument/hover', 'present')), {
      serviceAvailable: true,
    });
    expect(present.capabilities.hoverProvider).toBe(true);
  });

  it('puts no provider there for the same request marked absent', () => {
    const absent = planAdvertisement(
      declaring(
        capability('textDocument/hover', 'absent_permanent', {
          reason: 'a reason',
          instead: 'somewhere else',
        }),
      ),
      { serviceAvailable: true },
    );
    expect('hoverProvider' in absent.capabilities).toBe(false);
    expect(absent.registered).toEqual([]);
  });

  it('withholds an answer that needs the language service when the service is absent', () => {
    const declared = declaring(
      capability('textDocument/hover', 'present'),
      capability(VERSIONS_REQUEST, 'present'),
    );
    const plan = planAdvertisement(declared, { serviceAvailable: false });
    expect(plan.registered).toEqual([VERSIONS_REQUEST]);
    expect('hoverProvider' in plan.capabilities).toBe(false);
    const withheld = plan.skipped.find((entry) => entry.request === 'textDocument/hover');
    expect(withheld?.why).toContain('language service');
  });

  it('still answers the version request with no language service installed', () => {
    const plan = planAdvertisement(model, { serviceAvailable: false });
    expect(plan.registered).toContain(VERSIONS_REQUEST);
  });

  it('refuses a declaration that marks present a request nothing here answers', () => {
    const declared = declaring(capability(SignatureHelpRequest.method, 'present'));
    expect(() => planAdvertisement(declared, { serviceAvailable: true })).toThrow(
      SignatureHelpRequest.method,
    );
  });
});

describe('which documents this server serves', () => {
  it('serves the document kind the declaration gives it', () => {
    expect(serves(model, uriServedBy(model))).toBe(true);
  });

  it('does not serve a document kind the declaration gives the other server', () => {
    expect(serves(model, uriServedBy(source))).toBe(false);
  });

  it('answers a request about a document it does not serve as unsupported', () => {
    const error = unsupported(declaration, uriServedBy(source), SignatureHelpRequest.method);
    expect(error).toBeInstanceOf(ResponseError);
    expect(error.code).toBe(ErrorCodes.MethodNotFound);
    expect(error.message).toContain(source.id);
  });

  it('says so plainly when no declared server serves the document at all', () => {
    const error = unsupported(declaration, 'file:///a-document.unclaimed', VERSIONS_REQUEST);
    expect(error.message).toContain('no server');
  });
});

describe('the levels this server reports', () => {
  const report = versionReport(model.id);

  it('names the server the declaration names', () => {
    expect(report.server_id).toBe(model.id);
  });

  it('reports its own level from its manifest rather than from a literal', () => {
    expect(report.version).toBe(manifest.version ?? null);
  });

  it('reports every library it imports and no development dependency', () => {
    const imported = [
      ...new Set([
        ...Object.keys(manifest.dependencies ?? {}),
        ...Object.keys(manifest.peerDependencies ?? {}),
      ]),
    ].sort();
    expect(report.libraries.map((library) => library.name)).toEqual(imported);
    for (const name of Object.keys(manifest.devDependencies ?? {})) {
      if (imported.includes(name)) continue;
      expect(report.libraries.some((library) => library.name === name)).toBe(false);
    }
  });

  it('reads each level from the installed package rather than from what was asked for', () => {
    for (const library of report.libraries) {
      expect(library.level).toBe(installedLevel(library.name) ?? null);
    }
  });

  it('reports no level for a library that does not resolve here', () => {
    // Asked with a resolver that finds nothing, so this pins the rule rather than the state of
    // this checkout's node_modules. The facade is an optional peer: it is absent in a fresh
    // clone and in CI, and present the moment someone links a local build of it. The rule that
    // an unresolved library reports null holds in both, so the test must too.
    const unresolvable = versionReport(model.id, undefined, (id: string) => {
      throw new Error(`Cannot find module '${id}'`);
    });

    expect(unresolvable.libraries.length).toBeGreaterThan(0);
    for (const library of unresolvable.libraries) expect(library.level).toBeNull();
  });
});

describe('an answer the editor has moved past', () => {
  const uri = uriServedBy(model);
  const answer = { computed: 'against version one' };

  function opened(): ModelDocuments {
    const documents = new ModelDocuments();
    documents.open(uri, model.documents[0]?.languageId ?? '', 1, 'the first text');
    return documents;
  }

  it('is sent while the editor still holds the version it was computed against', () => {
    expect(currentOrDropped(opened(), uri, 1, answer)).toBe(answer);
  });

  it('is dropped once the editor has replaced that version', () => {
    const documents = opened();
    documents.update(uri, [{ text: 'the second text' }], 2);
    const dropped = currentOrDropped(documents, uri, 1, answer);
    expect(dropped).toBeInstanceOf(ResponseError);
    expect((dropped as ResponseError<void>).code).toBe(LSPErrorCodes.ContentModified);
  });

  it('is dropped once the editor has closed the document', () => {
    const documents = opened();
    documents.close(uri);
    expect(currentOrDropped(documents, uri, 1, answer)).toBeInstanceOf(ResponseError);
  });

  it('is dropped when the document reopens at a lower version than the answer', () => {
    const documents = opened();
    documents.close(uri);
    documents.open(uri, model.documents[0]?.languageId ?? '', 0, 'reopened');
    expect(currentOrDropped(documents, uri, 1, answer)).toBeInstanceOf(ResponseError);
  });
});

describe('a language service that is installed and broken', () => {
  // The absent case is covered in service.test.ts. This is the other one: the component resolves,
  // and then throws on the way up. `service.ts` re-throws that deliberately, so something has to
  // decide whether it is worth failing startup over, and the answer is no.

  it('does not take the server down', async () => {
    const broken = () => Promise.reject(new Error('boom from inside the component'));
    await expect(loadServiceForStartup(broken)).resolves.toMatchObject({ ok: false });
  });

  it('carries the component own error rather than an install instruction', async () => {
    const broken = () => Promise.reject(new Error('boom from inside the component'));
    const load = await loadServiceForStartup(broken);
    expect(load.ok).toBe(false);
    if (load.ok) return;
    expect(load.origin).toBe('component');
    expect(load.message).toContain('boom from inside the component');
    expect(load.message).not.toContain(NOT_INSTALLED);
  });

  it('leaves every model-text answer unadvertised, as an unreachable service must', async () => {
    const broken = () => Promise.reject(new Error('boom'));
    const load = await loadServiceForStartup(broken);
    const advertisement = planAdvertisement(model, { serviceAvailable: load.ok });
    expect(advertisement.registered).toContain('idfkit-lsp/versions');
    expect(advertisement.registered).not.toContain('textDocument/completion');
  });

  it('still answers what it can, which is what it is running', () => {
    // The point of staying up: a delivery path can still ask this server what it delivered.
    expect(versionReport('model').server_id).toBe('model');
  });
});
