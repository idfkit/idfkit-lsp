/**
 * Typed reader for the repository's one capability declaration.
 *
 * This server advertises what the root `capabilities.json` says it advertises, not what a list
 * beside the wiring says. The Python reader at `server/src/idfkit_lsp/capabilities.py` reads the
 * same file and applies the same rules; the two must agree, because a declaration that one runtime
 * accepts and the other refuses would mean the two servers disagree about the single story they are
 * supposed to tell together (Principle II).
 *
 * Every rule is checked at load and raises rather than returning, so no caller can carry on with a
 * half-read declaration. An editor told an answer exists when nobody can give it is worse off than
 * an editor told nothing, which is why a broken declaration must not reach a running server
 * (Principle IV).
 *
 * This module reads a record about the protocol. It holds no schema knowledge and no grammar, and
 * it depends on nothing beyond the Node standard library, because the running server imports it.
 */

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DECLARATION_FILENAME = 'capabilities.json';

/** The two servers this repository ships, named by what they serve rather than by their runtime. */
const KNOWN_SERVER_IDS = ['model', 'source'] as const;

export type ServerId = (typeof KNOWN_SERVER_IDS)[number];

/** What a server has to say about one protocol request. Three states and no fourth. */
export type CapabilityState = 'present' | 'absent_permanent' | 'absent_temporary';

const CAPABILITY_STATES: readonly CapabilityState[] = [
  'present',
  'absent_permanent',
  'absent_temporary',
];

/** One server's position on one protocol request. */
export interface Capability {
  readonly request: string;
  readonly state: CapabilityState;
  /** Why the absence is permanent. Present exactly when the state is `absent_permanent`. */
  readonly reason: string | undefined;
  /** What to use instead. Present exactly when the state is `absent_permanent`. */
  readonly instead: string | undefined;
  /** The item that closes the absence. Present exactly when the state is `absent_temporary`. */
  readonly tracked: string | undefined;
  /** Glue that cannot move into a server, so a reader knows it is unavailable elsewhere. */
  readonly editorSpecific: boolean;
}

/** A kind of document a server serves, as the editor identifies it. */
export interface DocumentKind {
  readonly languageId: string;
  readonly extensions: readonly string[];
}

/** One server: what it runs on, what it serves, and what it answers. */
export interface ServerDeclaration {
  readonly id: ServerId;
  readonly runtime: string;
  readonly documents: readonly DocumentKind[];
  readonly capabilities: readonly Capability[];
}

/** The whole of `capabilities.json`. */
export interface CapabilityDeclaration {
  readonly version: number;
  readonly servers: readonly ServerDeclaration[];
}

/**
 * A capability declaration broke one of its own rules.
 *
 * Thrown rather than reported so that a malformed declaration stops the server at startup instead
 * of producing an advertisement nobody can honour.
 */
export class DeclarationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DeclarationError';
  }
}

/**
 * Every request a server advertises. The wiring registers handlers from this rather than from a
 * list of its own, so the declaration and the running server cannot drift apart.
 */
export function presentRequests(server: ServerDeclaration): ReadonlySet<string> {
  return new Set(
    server.capabilities.filter((entry) => entry.state === 'present').map((entry) => entry.request),
  );
}

/** Every request a server states it does not answer, permanently or for now. */
export function absentRequests(server: ServerDeclaration): ReadonlySet<string> {
  return new Set(
    server.capabilities.filter((entry) => entry.state !== 'present').map((entry) => entry.request),
  );
}

/** This server's position on `request`, or `undefined` when it has stated none. */
export function capabilityFor(server: ServerDeclaration, request: string): Capability | undefined {
  return server.capabilities.find((entry) => entry.request === request);
}

/** One declared server by id. Throws rather than returning nothing, as the id is validated. */
export function serverById(
  declaration: CapabilityDeclaration,
  id: ServerId,
): ServerDeclaration {
  const found = declaration.servers.find((server) => server.id === id);
  if (found === undefined) {
    throw new DeclarationError(`server '${id}': rule 'a server id is declared' broken`);
  }
  return found;
}

/** Read and validate a capability declaration, defaulting to the repository root's. */
export function loadDeclaration(path?: string): CapabilityDeclaration {
  const resolved = path ?? defaultDeclarationPath();
  return parseDeclaration(resolved, readDeclaration(resolved));
}

/**
 * The root declaration, found by walking up from this module rather than from the cwd.
 *
 * Two layouts must both resolve. Under vitest and `tsc` this file sits at
 * `model-server/src/capabilities.ts`, three levels below the repository root. In a packaged
 * extension the bundle sits at `model-server/dist/main.js` and `capabilities.json` is kept at the
 * extension root (see `.vscodeignore`), which is the same walk. Resolving from the working
 * directory would break both, since an editor launches a server from wherever it pleases.
 */
function defaultDeclarationPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  let directory = here;
  for (;;) {
    const candidate = join(directory, DECLARATION_FILENAME);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  throw new DeclarationError(`no ${DECLARATION_FILENAME} above ${here}`);
}

function readDeclaration(path: string): unknown {
  let text: string;
  try {
    text = readFileSync(path, 'utf-8');
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new DeclarationError(`${path}: the capability declaration cannot be read: ${detail}`);
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new DeclarationError(`${path}: not valid JSON: ${detail}`);
  }
}

function parseDeclaration(where: string, raw: unknown): CapabilityDeclaration {
  const root = asObject(raw, where, 'the declaration');
  const version = root['version'];
  if (typeof version !== 'number' || !Number.isInteger(version)) {
    throw new DeclarationError(`${where}: rule 'version is an integer' broken`);
  }
  const servers = asArray(root['servers'], where, 'servers').map((entry) =>
    parseServer(where, entry),
  );
  checkDocumentsDisjoint(where, servers);
  checkServerSet(where, servers);
  return { version, servers };
}

function parseServer(where: string, raw: unknown): ServerDeclaration {
  const data = asObject(raw, where, 'a server entry');
  const id = asText(data['id'], where, 'a server entry', 'id');
  const subject = `server '${id}'`;
  const runtime = asText(data['runtime'], where, subject, 'runtime');
  const documents = asArray(data['documents'], where, `${subject}: documents`).map((entry) =>
    parseDocumentKind(where, id, entry),
  );
  if (documents.length === 0) {
    throw new DeclarationError(
      `${where}: ${subject}: rule 'a server serves a document kind' broken`,
    );
  }
  const capabilities = asArray(data['capabilities'], where, `${subject}: capabilities`).map(
    (entry) => parseCapability(where, id, entry),
  );
  if (capabilities.length === 0) {
    throw new DeclarationError(
      `${where}: ${subject}: rule 'a server states a position on some request' broken`,
    );
  }
  const seen = new Set<string>();
  for (const capability of capabilities) {
    if (seen.has(capability.request)) {
      throw new DeclarationError(
        `${where}: ${subject}, request '${capability.request}': ` +
          "rule 'a request appears once per server' broken",
      );
    }
    seen.add(capability.request);
  }
  return { id: asServerId(where, id), runtime, documents, capabilities };
}

function parseDocumentKind(where: string, serverId: string, raw: unknown): DocumentKind {
  const subject = `server '${serverId}'`;
  const data = asObject(raw, where, `${subject}: a document kind`);
  const languageId = asText(data['language_id'], where, subject, 'language_id');
  const extensions = asArray(data['extensions'], where, `${subject}: extensions`).map((entry) =>
    asText(entry, where, `${subject}, language id '${languageId}'`, 'extension'),
  );
  if (extensions.length === 0) {
    throw new DeclarationError(
      `${where}: ${subject}, language id '${languageId}': ` +
        "rule 'a document kind names an extension' broken",
    );
  }
  return { languageId, extensions };
}

function parseCapability(where: string, serverId: string, raw: unknown): Capability {
  const data = asObject(raw, where, `server '${serverId}': a capability`);
  const request = asText(data['request'], where, `server '${serverId}'`, 'request');
  const subject = `server '${serverId}', request '${request}'`;
  const rawState = asText(data['state'], where, subject, 'state');
  if (!isCapabilityState(rawState)) {
    const known = [...CAPABILITY_STATES].sort().join(', ');
    throw new DeclarationError(
      `${where}: ${subject}: rule 'state is one of ${known}' broken: '${rawState}'`,
    );
  }
  const reason = asOptionalText(data['reason'], where, subject, 'reason');
  const instead = asOptionalText(data['instead'], where, subject, 'instead');
  const tracked = asOptionalText(data['tracked'], where, subject, 'tracked');
  const rawEditorSpecific = data['editor_specific'] ?? false;
  if (typeof rawEditorSpecific !== 'boolean') {
    throw new DeclarationError(`${where}: ${subject}: rule 'editor_specific is a boolean' broken`);
  }

  // A permanent absence that says neither why nor what to use instead is the silence this whole
  // declaration exists to end, so it fails at load rather than reaching a reader.
  if (rawState === 'absent_permanent') {
    if (reason === undefined) {
      throw new DeclarationError(
        `${where}: ${subject}: rule 'absent_permanent states a reason' broken`,
      );
    }
    if (instead === undefined) {
      throw new DeclarationError(
        `${where}: ${subject}: rule 'absent_permanent names what to use instead' broken`,
      );
    }
  } else if (rawState === 'absent_temporary') {
    if (tracked === undefined) {
      throw new DeclarationError(
        `${where}: ${subject}: rule 'absent_temporary names the tracked item' broken`,
      );
    }
  } else {
    const carried = (
      [
        ['reason', reason],
        ['instead', instead],
        ['tracked', tracked],
      ] as const
    )
      .filter(([, value]) => value !== undefined)
      .map(([name]) => name);
    if (carried.length > 0) {
      throw new DeclarationError(
        `${where}: ${subject}: rule 'present carries no reason, instead, or tracked' broken: ` +
          `carries ${carried.join(', ')}`,
      );
    }
  }
  return {
    request,
    state: rawState,
    reason,
    instead,
    tracked,
    editorSpecific: rawEditorSpecific,
  };
}

/** No document kind may be claimed twice: the client routes on exactly one owner. */
function checkDocumentsDisjoint(where: string, servers: readonly ServerDeclaration[]): void {
  const languageOwner = new Map<string, string>();
  const extensionOwner = new Map<string, string>();
  for (const server of servers) {
    for (const document of server.documents) {
      const owner = languageOwner.get(document.languageId);
      if (owner !== undefined) {
        throw new DeclarationError(
          `${where}: servers '${owner}' and '${server.id}': ` +
            `rule 'one server per language id' broken: '${document.languageId}'`,
        );
      }
      languageOwner.set(document.languageId, server.id);
      for (const extension of document.extensions) {
        const holder = extensionOwner.get(extension);
        if (holder !== undefined) {
          throw new DeclarationError(
            `${where}: servers '${holder}' and '${server.id}': ` +
              `rule 'one server per extension' broken: '${extension}'`,
          );
        }
        extensionOwner.set(extension, server.id);
      }
    }
  }
}

function checkServerSet(where: string, servers: readonly ServerDeclaration[]): void {
  if (servers.length < 2) {
    throw new DeclarationError(
      `${where}: rule 'two servers are declared, one per document kind' broken: ` +
        `${servers.length} declared`,
    );
  }
  const declared = new Set(servers.map((server) => server.id));
  for (const id of KNOWN_SERVER_IDS) {
    if (!declared.has(id)) {
      throw new DeclarationError(
        `${where}: rule 'each server id is declared once' broken: '${id}' is not declared`,
      );
    }
  }
}

function asServerId(where: string, id: string): ServerId {
  for (const known of KNOWN_SERVER_IDS) {
    if (id === known) return known;
  }
  const listed = [...KNOWN_SERVER_IDS].sort().join(', ');
  throw new DeclarationError(
    `${where}: server '${id}': rule 'a server id is one of ${listed}' broken`,
  );
}

function isCapabilityState(value: string): value is CapabilityState {
  return (CAPABILITY_STATES as readonly string[]).includes(value);
}

function asObject(value: unknown, where: string, subject: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new DeclarationError(`${where}: ${subject}: rule 'is a JSON object' broken`);
  }
  return value as Record<string, unknown>;
}

function asArray(value: unknown, where: string, subject: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new DeclarationError(`${where}: ${subject}: rule 'is a JSON array' broken`);
  }
  return value as unknown[];
}

function asText(value: unknown, where: string, subject: string, key: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new DeclarationError(
      `${where}: ${subject}: rule '${key} is a non-empty string' broken`,
    );
  }
  return value;
}

function asOptionalText(
  value: unknown,
  where: string,
  subject: string,
  key: string,
): string | undefined {
  if (value === undefined || value === null) return undefined;
  return asText(value, where, subject, key);
}
