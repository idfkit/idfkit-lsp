/**
 * The model server's protocol wiring: stdio in, stdio out, and nothing decided here.
 *
 * Three rules shape this file, and every branch below follows from one of them.
 *
 * WHAT IS ADVERTISED COMES FROM THE DECLARATION. `capabilities.json` says what this server
 * answers, and `planAdvertisement` turns that into the `initialize` result and into the set of
 * handlers that get registered. There is no list of advertised requests written here: the table
 * below says which handler answers which request and what that answer needs, and the declaration
 * decides which of them the editor is ever told about. Today the five model-text answers are
 * `absent_temporary`, so this server advertises the version request and nothing else, which is the
 * declaration being right rather than this file being unfinished (Principle II).
 *
 * AN ANSWER THIS SERVER CANNOT GIVE IS NOT GIVEN. A request marked present whose answer needs the
 * language service is not advertised when the language service is not installed, because an editor
 * told an answer exists that nobody can give is worse off than an editor told nothing (Principle
 * IV). The absence itself is a message: the guard's own words reach the user through
 * `window/showMessage` and `window/logMessage`, the server stays up answering the version request,
 * and the source server, which serves Python source, never hears about any of it.
 *
 * NOTHING HERE KNOWS WHAT A MODEL SAYS. Every answer below is a translation of something the
 * language service returned, positioned through `positions.ts` and passed to a handler module. The
 * completion provider advertises no trigger characters on purpose: which character begins a field
 * is a fact about the format, and writing one here would be the grammar this repository may not
 * hold (Principle I).
 */

import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  CompletionRequest,
  DefinitionRequest,
  DocumentDiagnosticRequest,
  ErrorCodes,
  HoverRequest,
  LSPErrorCodes,
  MessageType,
  ProposedFeatures,
  PublishDiagnosticsNotification,
  ResponseError,
  SemanticTokensRegistrationType,
  SemanticTokensRequest,
  ShowMessageNotification,
  TextDocumentSyncKind,
  createConnection,
} from 'vscode-languageserver/node';

import { loadDeclaration, presentRequests, serverById } from './capabilities.js';
import { ModelDocuments } from './documents.js';
import { completionFor } from './handlers/completion.js';
import { definitionFor } from './handlers/definition.js';
import {
  diagnosticsDelivery,
  fullDocumentReport,
  publishDiagnosticsFor,
} from './handlers/diagnostics.js';
import { hoverFor } from './handlers/hover.js';
import { TokenLegend, semanticTokensFor } from './handlers/semanticTokens.js';
import { LineIndex } from './positions.js';
import { loadLanguageService } from './service.js';

import type { CapabilityDeclaration, ServerDeclaration } from './capabilities.js';
import type { ModelDocument } from './documents.js';
import type {
  ClassifiedRegion,
  IdfDocument,
  LanguageService,
  ProsePool,
  Schema,
} from './language-service.js';
import type { PositionEncoding } from './positions.js';
import type { LanguageServiceLoad, SubpathImport } from './service.js';
import type {
  ClientCapabilities,
  CompletionParams,
  Connection,
  DefinitionParams,
  Disposable,
  DocumentDiagnosticParams,
  HoverParams,
  InitializeParams,
  InitializeResult,
  SemanticTokens,
  SemanticTokensLegend,
  SemanticTokensParams,
  ServerCapabilities,
} from 'vscode-languageserver';

/** The id this file wires. The other id in the declaration belongs to the Python server. */
const SERVER_ID = 'model';

/** This repository's own request, which is not the protocol's and so has no constant to borrow. */
export const VERSIONS_REQUEST = 'idfkit-lsp/versions';

/** Every manifest is read by the same name, this server's own included. */
const MANIFEST = 'package.json';

// ---------------------------------------------------------------------------
// The unit the client and this server settle on
// ---------------------------------------------------------------------------

/**
 * The protocol's encoding names, spelled as `positions.ts` spells them.
 *
 * The two spellings are the same three strings and this is the one place they meet. A client that
 * offers something else is offering a unit this server cannot convert into, so it is passed over
 * rather than accepted and mis-measured.
 */
const NEGOTIABLE: readonly PositionEncoding[] = ['utf-8', 'utf-16', 'utf-32'];

/** What the protocol requires of every client, and so what an unstated preference means. */
const DEFAULT_ENCODING: PositionEncoding = 'utf-16';

function asPositionEncoding(kind: string): PositionEncoding | undefined {
  return NEGOTIABLE.find((known) => known === kind);
}

/**
 * The unit to answer in.
 *
 * The client's list is in the client's order of preference, so the first entry this server can
 * convert into is the one both sides are happiest with.
 */
export function negotiateEncoding(capabilities: ClientCapabilities | undefined): PositionEncoding {
  for (const offered of capabilities?.general?.positionEncodings ?? []) {
    const known = asPositionEncoding(offered);
    if (known !== undefined) return known;
  }
  return DEFAULT_ENCODING;
}

// ---------------------------------------------------------------------------
// Which documents this server serves
// ---------------------------------------------------------------------------

/** The extensions a server is given, lowercased so a URI can be matched against them. */
export function servedExtensions(declared: ServerDeclaration): ReadonlySet<string> {
  const extensions = new Set<string>();
  for (const kind of declared.documents) {
    for (const extension of kind.extensions) extensions.add(extension.toLowerCase());
  }
  return extensions;
}

/** Whether a URI names a document this server serves. The declaration decides, nothing else. */
export function serves(declared: ServerDeclaration, uri: string): boolean {
  const lowered = uri.toLowerCase();
  for (const extension of servedExtensions(declared)) {
    if (lowered.endsWith(extension)) return true;
  }
  return false;
}

/** Which declared server serves a URI, or nothing when no server claims that kind of document. */
export function serverFor(
  declaration: CapabilityDeclaration,
  uri: string,
): ServerDeclaration | undefined {
  return declaration.servers.find((server) => serves(server, uri));
}

/**
 * The answer to a request about a document this server does not serve.
 *
 * Method-not-found rather than a null: a null would say this server looked and found nothing,
 * which is a claim about the document. The message names the server that does serve it where the
 * declaration knows of one, so the reply is a direction rather than a refusal.
 */
export function unsupported(
  declaration: CapabilityDeclaration,
  uri: string,
  request: string,
): ResponseError<void> {
  const owner = serverFor(declaration, uri);
  const instead =
    owner === undefined
      ? 'no server in this repository serves that kind of document'
      : `the '${owner.id}' server serves it`;
  return new ResponseError(
    ErrorCodes.MethodNotFound,
    `the '${SERVER_ID}' server does not serve ${uri}, so it answers no ${request} about it: ` +
      `${instead}.`,
  );
}

// ---------------------------------------------------------------------------
// Answers the editor has already moved past
// ---------------------------------------------------------------------------

export const SUPERSEDED =
  'the document changed while this answer was being computed, so the answer was dropped rather ' +
  'than sent against text the editor no longer has';

/**
 * The answer, or the protocol's way of saying it arrived too late.
 *
 * `contracts/model-server.md` point 6. The comparison is `documents.isSuperseded`, which is
 * inequality rather than "greater than" so that a document closed and reopened is caught too.
 * `ContentModified` is the code the protocol reserves for exactly this, and a client is expected
 * to swallow it rather than show it.
 */
export function currentOrDropped<T>(
  documents: ModelDocuments,
  uri: string,
  version: number,
  answer: T,
): T | ResponseError<void> {
  if (!documents.isSuperseded(uri, version)) return answer;
  return new ResponseError(LSPErrorCodes.ContentModified, SUPERSEDED);
}

// ---------------------------------------------------------------------------
// What the caller supplies alongside the text
// ---------------------------------------------------------------------------

/**
 * The inputs the language service takes but does not produce.
 *
 * Feature 005 fixes five answers as pure functions of text and schema, and it is the caller that
 * resolves the schema, parses the model, loads the prose, and asks the syntax layer to classify.
 * All four come from `idfkit` itself rather than from the language service, which is why
 * `service.ts` does not reach them: it holds the one import of `idfkit/language`, and naming
 * `classify` there would give a reader two names for one function.
 *
 * NOTHING RESOLVES THEM TODAY. This repository installs neither `idfkit` nor its language service,
 * so every member below returns nothing and every handler that needs one says it cannot answer
 * instead of assembling something (Principle IV). The day the two are installed, this interface is
 * where that resolution lands, and no handler changes.
 */
export interface CallerInputs {
  /** A schema for the version this text declares, or nothing when none can be resolved. */
  schemaFor(text: string): Schema | undefined;
  /** The syntax layer's classification of the whole text, or nothing when it cannot be had. */
  classify(text: string): readonly ClassifiedRegion[] | undefined;
  /** The parsed model, which supplies declarations and reference candidates. */
  documentFor(text: string): IdfDocument | undefined;
  /** The prose the schema's own wording is drawn from, when a pool has been loaded. */
  proseFor(text: string): ProsePool | undefined;
}

/** What this repository can supply today, which is nothing, stated rather than approximated. */
export const NOTHING_RESOLVED: CallerInputs = {
  schemaFor: () => undefined,
  classify: () => undefined,
  documentFor: () => undefined,
  proseFor: () => undefined,
};

/** Said once per request that could not be answered, naming the input that was missing. */
const NO_SCHEMA =
  'no schema could be resolved for this text, so this server has nothing to answer from and ' +
  'answers nothing rather than guessing';
const NO_SYNTAX_LAYER =
  'the syntax layer did not classify this text, so this server has no regions to translate';
const NO_MODEL =
  'the model behind this text could not be read, so this server has no declarations to report';

// ---------------------------------------------------------------------------
// Levels, read from what is installed rather than written here
// ---------------------------------------------------------------------------

/** One library this server resolved, and the level it reached. `null` where it reached none. */
export interface LibraryLevel {
  readonly name: string;
  readonly level: string | null;
}

/**
 * This server's answer to `idfkit-lsp/versions`, in the shape the source server answers in.
 *
 * The two servers answer the same question, so a reader who has seen one answer has seen both.
 */
export interface VersionReport {
  readonly server_id: string;
  readonly version: string | null;
  readonly libraries: readonly LibraryLevel[];
}

/** A package manifest, in the members this file reads. */
interface Manifest {
  readonly name: string | undefined;
  readonly version: string | undefined;
  readonly dependencies: Readonly<Record<string, string>>;
  readonly peerDependencies: Readonly<Record<string, string>>;
}

function asRecord(value: unknown): Readonly<Record<string, string>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {};
  const entries = Object.entries(value as Record<string, unknown>).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string',
  );
  return Object.fromEntries(entries);
}

function readManifest(path: string): Manifest | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, 'utf-8')) as unknown;
  } catch {
    return undefined;
  }
  if (typeof parsed !== 'object' || parsed === null) return undefined;
  const data = parsed as Record<string, unknown>;
  return {
    name: typeof data['name'] === 'string' ? data['name'] : undefined,
    version: typeof data['version'] === 'string' ? data['version'] : undefined,
    dependencies: asRecord(data['dependencies']),
    peerDependencies: asRecord(data['peerDependencies']),
  };
}

/** The first manifest at or above a directory. */
function manifestAbove(directory: string): Manifest | undefined {
  let here = directory;
  for (;;) {
    const candidate = join(here, MANIFEST);
    if (existsSync(candidate)) {
      const manifest = readManifest(candidate);
      if (manifest !== undefined) return manifest;
    }
    const parent = dirname(here);
    if (parent === here) return undefined;
    here = parent;
  }
}

/** This server's own manifest, found by walking up from this module rather than from the cwd. */
export function ownManifest(): Manifest | undefined {
  return manifestAbove(dirname(fileURLToPath(import.meta.url)));
}

const require = createRequire(import.meta.url);

/**
 * The level a library actually resolved to, read from the installed package's own manifest.
 *
 * Not read from this server's manifest, which states what was asked for: a delivery path that
 * installed something other than what it named is visible in the answer rather than in a user's
 * confusion. A library that resolves to nothing has no level, and no level is invented for it.
 */
export function levelOf(
  name: string,
  resolveFrom: (id: string) => string = require.resolve,
): string | null {
  let entry: string;
  try {
    entry = resolveFrom(name);
  } catch {
    return null;
  }
  let here = dirname(entry);
  for (;;) {
    const candidate = join(here, MANIFEST);
    if (existsSync(candidate)) {
      const manifest = readManifest(candidate);
      // A nested manifest carrying no name is packaging, not the package: keep walking.
      if (manifest?.name === name) return manifest.version ?? null;
    }
    const parent = dirname(here);
    if (parent === here) return null;
    here = parent;
  }
}

/**
 * Every library this server imports, with the level each one actually resolved to.
 *
 * The names come from this server's own manifest rather than from a list in this file, so a
 * dependency added or renamed is reported without anyone editing the report. A development
 * dependency is not reported: a test runner is installed, and a running server does not import it.
 */
export function versionReport(
  serverId: string,
  manifest: Manifest | undefined = ownManifest(),
  resolveFrom: (id: string) => string = require.resolve,
): VersionReport {
  const names = [
    ...new Set([
      ...Object.keys(manifest?.dependencies ?? {}),
      ...Object.keys(manifest?.peerDependencies ?? {}),
    ]),
  ].sort();
  return {
    server_id: serverId,
    version: manifest?.version ?? null,
    libraries: names.map((name) => ({ name, level: levelOf(name, resolveFrom) })),
  };
}

// ---------------------------------------------------------------------------
// The table: one entry per request this wiring can answer
// ---------------------------------------------------------------------------

/** What the client can be told about the legend and about re-registration, at advertising time. */
export interface Negotiated {
  /** The legend as it stands. Empty until the language service names a kind. */
  readonly legend: TokenLegend;
  /** Whether the client accepts a registration after `initialize`, and so a grown legend. */
  readonly dynamicSemanticTokens: boolean;
}

/** The legend as the protocol takes it: the same entries, in an array the protocol may hold. */
function protocolLegend(legend: TokenLegend): SemanticTokensLegend {
  return { tokenTypes: [...legend.tokenTypes], tokenModifiers: [...legend.tokenModifiers] };
}

interface AnswerShape {
  /** Whether producing this answer needs the language service. */
  readonly needsService: boolean;
  /**
   * How the request appears in what `initialize` returns, or nothing where the protocol carries
   * no provider for it and the declaration is the only place it is announced.
   */
  readonly advertise: ((into: ServerCapabilities, negotiated: Negotiated) => void) | undefined;
}

/**
 * Every request this file supplies a handler for. Not what is advertised: the declaration decides
 * that, and this table only says what there is to advertise and what each answer costs.
 */
const ANSWERS: ReadonlyMap<string, AnswerShape> = new Map<string, AnswerShape>([
  [VERSIONS_REQUEST, { needsService: false, advertise: undefined }],
  [
    SemanticTokensRequest.method,
    {
      needsService: true,
      advertise: (into, negotiated) => {
        // A client that can be registered with a new legend is registered after `initialize`
        // instead, because the legend grows as the service names kinds and a legend fixed here
        // would leave the client unable to read the indices of anything named later.
        if (negotiated.dynamicSemanticTokens) return;
        into.semanticTokensProvider = { legend: protocolLegend(negotiated.legend), full: true };
      },
    },
  ],
  [
    DocumentDiagnosticRequest.method,
    {
      needsService: true,
      advertise: (into) => {
        into.diagnosticProvider = { interFileDependencies: false, workspaceDiagnostics: false };
      },
    },
  ],
  [PublishDiagnosticsNotification.method, { needsService: true, advertise: undefined }],
  [
    CompletionRequest.method,
    {
      needsService: true,
      advertise: (into) => {
        // No trigger characters. Which character begins a field is a fact about the format, and
        // naming one here would be grammar this repository may not hold.
        into.completionProvider = { resolveProvider: false };
      },
    },
  ],
  [
    HoverRequest.method,
    {
      needsService: true,
      advertise: (into) => {
        into.hoverProvider = true;
      },
    },
  ],
  [
    DefinitionRequest.method,
    {
      needsService: true,
      advertise: (into) => {
        into.definitionProvider = true;
      },
    },
  ],
]);

/** One request the declaration marks present that this server will not be advertising, and why. */
export interface Skipped {
  readonly request: string;
  readonly why: string;
}

/** What the declaration made of the handlers this file supplies. */
export interface Advertisement {
  readonly registered: readonly string[];
  readonly skipped: readonly Skipped[];
  readonly capabilities: ServerCapabilities;
}

export interface AdvertiseOptions {
  /** Whether the language service loaded. A request that needs it is not advertised without it. */
  readonly serviceAvailable: boolean;
  readonly negotiated?: Negotiated;
}

/**
 * Reach the language service without letting a broken one take the whole server down.
 *
 * `loadLanguageService` re-throws anything that is not the facade's own guard, which is right for
 * it: a component that is installed and broken is not a component that is missing, and telling
 * someone to install what they already have would be the wrong message. It is not a reason to fail
 * `initialize`, though. A rejected initialize is a server that is not there at all, and this one
 * still owes an answer to `idfkit-lsp/versions`, still has to say plainly what went wrong, and
 * still has to leave the source server serving. So the throw is caught here and reported as what
 * it is, carrying the component's own error rather than an install instruction.
 */
export async function loadServiceForStartup(
  load?: SubpathImport
): Promise<LanguageServiceLoad> {
  try {
    return load === undefined ? await loadLanguageService() : await loadLanguageService(load);
  } catch (error: unknown) {
    const detail = error instanceof Error ? (error.stack ?? error.message) : String(error);
    return {
      ok: false,
      origin: 'component',
      message: `The language service is installed but could not be loaded: ${detail}`,
    };
  }
}


function whyAbsent(declared: ServerDeclaration, request: string): string {
  const capability = declared.capabilities.find((entry) => entry.request === request);
  if (capability === undefined) return 'the declaration states no position on it';
  if (capability.state === 'absent_permanent') {
    return `${capability.state}: ${capability.reason ?? ''} Instead: ${capability.instead ?? ''}`;
  }
  return `${capability.state}: ${capability.tracked ?? ''}`;
}

/**
 * What to advertise and what to register, read from the declaration.
 *
 * Throws where the declaration marks a request present that nothing here answers, on the same
 * reasoning as the Python server's registration: an editor would be told an answer exists that
 * nothing in this process gives.
 */
export function planAdvertisement(
  declared: ServerDeclaration,
  options: AdvertiseOptions,
): Advertisement {
  const negotiated: Negotiated = options.negotiated ?? {
    legend: new TokenLegend(),
    dynamicSemanticTokens: false,
  };
  const capabilities: ServerCapabilities = {};
  const registered: string[] = [];
  const skipped: Skipped[] = [];

  for (const request of [...presentRequests(declared)].sort()) {
    const answer = ANSWERS.get(request);
    if (answer === undefined) {
      throw new Error(
        `the capability declaration marks '${request}' present for the '${declared.id}' server, ` +
          'but no handler is wired for it: an editor would be told an answer exists ' +
          'that nothing here gives',
      );
    }
    if (answer.needsService && !options.serviceAvailable) {
      skipped.push({
        request,
        why: 'the language service is not installed, so this server would be advertising an ' +
          'answer it cannot give',
      });
      continue;
    }
    answer.advertise?.(capabilities, negotiated);
    registered.push(request);
  }

  for (const request of [...ANSWERS.keys()].sort()) {
    if (registered.includes(request)) continue;
    if (skipped.some((entry) => entry.request === request)) continue;
    skipped.push({ request, why: whyAbsent(declared, request) });
  }

  return { registered, skipped, capabilities };
}

/** The advertisement in one line, so a reader of the log sees the declaration take effect. */
export function describeAdvertisement(advertisement: Advertisement): string {
  const registered = advertisement.registered.join(', ') || 'nothing';
  const skipped =
    advertisement.skipped.map((entry) => `${entry.request} (${entry.why})`).join('; ') ||
    'nothing';
  return `advertised from the declaration: ${registered}; not advertised: ${skipped}`;
}

// ---------------------------------------------------------------------------
// The server
// ---------------------------------------------------------------------------

export interface ModelServerOptions {
  readonly declaration?: CapabilityDeclaration;
  readonly inputs?: CallerInputs;
}

/**
 * The wiring itself: one connection, one document store, one legend, one service.
 *
 * Every handler follows the same four steps, which is the whole of what this class does. Refuse a
 * document this server does not serve. Take the text and the negotiated unit. Ask the service.
 * Drop the answer if the editor has moved past the version it was computed against.
 */
class ModelServer {
  readonly #connection: Connection;
  readonly #declaration: CapabilityDeclaration;
  readonly #declared: ServerDeclaration;
  readonly #documents = new ModelDocuments();
  readonly #legend = new TokenLegend();
  readonly #inputs: CallerInputs;

  #service: LanguageService | undefined;
  #absence: string | undefined;
  #advertisement: Advertisement | undefined;
  #publishOnChange = false;
  #dynamicSemanticTokens = false;
  #semanticRegistration: Disposable | undefined;
  #legendRefreshSupported = false;

  constructor(connection: Connection, options: ModelServerOptions = {}) {
    this.#connection = connection;
    this.#declaration = options.declaration ?? loadDeclaration();
    this.#declared = serverById(this.#declaration, SERVER_ID);
    this.#inputs = options.inputs ?? NOTHING_RESOLVED;
  }

  listen(): void {
    this.#connection.onInitialize((params) => this.#initialize(params));
    this.#connection.onInitialized(() => this.#initialized());
    this.#synchronise();
    this.#connection.listen();
  }

  // --- lifecycle ---

  async #initialize(params: InitializeParams): Promise<InitializeResult> {
    const encoding = negotiateEncoding(params.capabilities);
    this.#documents.negotiate(encoding);
    this.#dynamicSemanticTokens =
      params.capabilities.textDocument?.semanticTokens?.dynamicRegistration === true;
    this.#legendRefreshSupported =
      params.capabilities.workspace?.semanticTokens?.refreshSupport === true;

    // Awaited before the answer goes out, so what this server advertises already accounts for
    // whether the component every model-text answer comes from is there at all.
    //
    // `loadLanguageService` re-throws anything that is not the facade's own guard, which is right
    // for it: a component that is installed and broken is not a component that is missing, and
    // telling someone to install what they already have would be the wrong message. It is not a
    // reason to fail `initialize`, though. A rejected initialize is a server that is not there at
    // all, and this server still owes an answer to `idfkit-lsp/versions` and still has to leave
    // the source server serving. So the throw is caught here and reported as what it is.
    const load = await loadServiceForStartup();
    if (load.ok) {
      this.#service = load.service;
    } else {
      this.#absence = load.message;
    }

    const advertisement = planAdvertisement(this.#declared, {
      serviceAvailable: load.ok,
      negotiated: { legend: this.#legend, dynamicSemanticTokens: this.#dynamicSemanticTokens },
    });
    this.#advertisement = advertisement;
    this.#install(advertisement);
    this.#publishOnChange =
      advertisement.registered.includes(PublishDiagnosticsNotification.method) &&
      diagnosticsDelivery(params.capabilities) === 'onChange';

    const manifest = ownManifest();
    return {
      capabilities: {
        ...advertisement.capabilities,
        positionEncoding: encoding,
        // Lifecycle and synchronisation are not advertised capabilities: an editor sends them to
        // every server it starts, and a server that ignored them would hold no documents to
        // answer about. Incremental, so a keystroke costs a change rather than a whole file.
        textDocumentSync: { openClose: true, change: TextDocumentSyncKind.Incremental },
      },
      ...(manifest?.name === undefined
        ? {}
        : {
            serverInfo: {
              name: manifest.name,
              ...(manifest.version === undefined ? {} : { version: manifest.version }),
            },
          }),
    };
  }

  #initialized(): void {
    const advertisement = this.#advertisement;
    if (advertisement !== undefined) {
      this.#connection.console.info(describeAdvertisement(advertisement));
    }

    // The guard's words, unchanged. It already names what to install, says why the component is
    // optional, and says what still works without it; rewording it here would replace a message
    // written where the facts are known with one written where they are not.
    const absence = this.#absence;
    if (absence !== undefined) {
      this.#connection.console.warn(absence);
      // A notification rather than the request `showWarningMessage` sends: this message asks the
      // reader for nothing, and a request would leave one outstanding on a client that never
      // answers it.
      void this.#connection.sendNotification(ShowMessageNotification.type, {
        type: MessageType.Warning,
        message: absence,
      });
    }

    const tokensRegistered =
      advertisement?.registered.includes(SemanticTokensRequest.method) === true;
    if (this.#dynamicSemanticTokens && tokensRegistered) {
      void this.#registerSemanticTokens();
    }
  }

  #synchronise(): void {
    this.#connection.onDidOpenTextDocument((params) => {
      const { textDocument } = params;
      if (!serves(this.#declared, textDocument.uri)) {
        this.#connection.console.info(
          `${textDocument.uri} is not a document the '${SERVER_ID}' server serves, ` +
            'so it is not held',
        );
        return;
      }
      const document = this.#documents.open(
        textDocument.uri,
        textDocument.languageId,
        textDocument.version,
        textDocument.text,
      );
      this.#publish(document);
    });

    this.#connection.onDidChangeTextDocument((params) => {
      const document = this.#documents.update(
        params.textDocument.uri,
        params.contentChanges,
        params.textDocument.version,
      );
      if (document === undefined) return;
      this.#publish(document);
    });

    this.#connection.onDidCloseTextDocument((params) => {
      const { uri } = params.textDocument;
      const held = this.#documents.get(uri) !== undefined;
      this.#documents.close(uri);
      // Clearing what was published is not a finding about the document; it is taking back
      // findings that no longer have a document to be about.
      if (held && this.#publishOnChange) {
        this.#connection.sendDiagnostics({ uri, diagnostics: [] });
      }
    });
  }

  // --- registration ---

  #install(advertisement: Advertisement): void {
    for (const request of advertisement.registered) {
      switch (request) {
        case VERSIONS_REQUEST:
          this.#connection.onRequest(request, () => versionReport(this.#declared.id));
          break;
        case SemanticTokensRequest.method:
          this.#connection.onRequest(request, (params: SemanticTokensParams) =>
            this.#semanticTokens(params),
          );
          break;
        case DocumentDiagnosticRequest.method:
          this.#connection.onRequest(request, (params: DocumentDiagnosticParams) =>
            this.#diagnostic(params),
          );
          break;
        case CompletionRequest.method:
          this.#connection.onRequest(request, (params: CompletionParams) =>
            this.#completion(params),
          );
          break;
        case HoverRequest.method:
          this.#connection.onRequest(request, (params: HoverParams) => this.#hover(params));
          break;
        case DefinitionRequest.method:
          this.#connection.onRequest(request, (params: DefinitionParams) =>
            this.#definition(params),
          );
          break;
        case PublishDiagnosticsNotification.method:
          // A notification this server sends rather than a request it answers. `#publish` is
          // where it happens, and `#publishOnChange` is what turns it on.
          break;
        default:
          throw new Error(
            `'${request}' is advertised for the '${this.#declared.id}' server but this wiring ` +
              'installs no handler for it',
          );
      }
    }
  }

  // --- the five answers ---

  #semanticTokens(params: SemanticTokensParams): SemanticTokens | ResponseError<void> | null {
    const held = this.#held(params.textDocument.uri, SemanticTokensRequest.method);
    if (held instanceof ResponseError || held === undefined) return held ?? null;
    const regions = this.#inputs.classify(held.text);
    if (regions === undefined) return this.#nothing(SemanticTokensRequest.method, NO_SYNTAX_LAYER);

    const before = this.#legend.generation;
    const payload = semanticTokensFor(regions, this.#lines(held), this.#legend);
    if (this.#legend.generation !== before) void this.#legendGrew();
    return this.#current(held, { data: [...payload.data] });
  }

  #diagnostic(params: DocumentDiagnosticParams): unknown {
    const held = this.#held(params.textDocument.uri, DocumentDiagnosticRequest.method);
    if (held instanceof ResponseError || held === undefined) return held ?? null;
    const service = this.#service;
    const schema = this.#inputs.schemaFor(held.text);
    if (service === undefined || schema === undefined) {
      // Not an empty report: an empty report says the document has no findings, which is a claim
      // about the document rather than about this server.
      return new ResponseError(LSPErrorCodes.RequestFailed, NO_SCHEMA);
    }
    const findings = service.findingsIn(held.text, schema);
    return this.#current(held, fullDocumentReport(findings, this.#lines(held)));
  }

  #completion(params: CompletionParams): unknown {
    const held = this.#held(params.textDocument.uri, CompletionRequest.method);
    if (held instanceof ResponseError || held === undefined) return held ?? null;
    const service = this.#service;
    const schema = this.#inputs.schemaFor(held.text);
    if (service === undefined || schema === undefined) {
      return this.#nothing(CompletionRequest.method, NO_SCHEMA);
    }
    const lines = this.#lines(held);
    const document = this.#inputs.documentFor(held.text);
    const prose = this.#inputs.proseFor(held.text);
    const answer = completionFor(
      service.completionsAt(held.text, lines.offsetAt(params.position), schema, {
        ...(document === undefined ? {} : { document }),
        ...(prose === undefined ? {} : { prose }),
      }),
      lines,
    );
    if (answer.kind === 'cannotAnswer') {
      // Incomplete rather than complete-and-empty: a complete empty list would say the schema
      // permits nothing here, which is a different claim and a false one.
      this.#connection.console.info(
        `${CompletionRequest.method}: no answer could be produced (${answer.absence.reason})`,
      );
      return { isIncomplete: true, items: [] };
    }
    return this.#current(held, answer.list);
  }

  #hover(params: HoverParams): unknown {
    const held = this.#held(params.textDocument.uri, HoverRequest.method);
    if (held instanceof ResponseError || held === undefined) return held ?? null;
    const service = this.#service;
    const schema = this.#inputs.schemaFor(held.text);
    if (service === undefined || schema === undefined) {
      return this.#nothing(HoverRequest.method, NO_SCHEMA);
    }
    const lines = this.#lines(held);
    const prose = this.#inputs.proseFor(held.text);
    const answer = hoverFor(
      service.explainAt(held.text, lines.offsetAt(params.position), schema, prose),
      lines,
    );
    if (answer.kind === 'nothing') return null;
    return this.#current(held, answer.hover);
  }

  #definition(params: DefinitionParams): unknown {
    const held = this.#held(params.textDocument.uri, DefinitionRequest.method);
    if (held instanceof ResponseError || held === undefined) return held ?? null;
    const service = this.#service;
    const schema = this.#inputs.schemaFor(held.text);
    if (service === undefined || schema === undefined) {
      return this.#nothing(DefinitionRequest.method, NO_SCHEMA);
    }
    const model = this.#inputs.documentFor(held.text);
    if (model === undefined) return this.#nothing(DefinitionRequest.method, NO_MODEL);
    const lines = this.#lines(held);
    const answer = definitionFor(
      service.declarationAt(held.text, lines.offsetAt(params.position), schema, model),
      held.uri,
      lines,
    );
    if (answer.kind === 'nothing') return null;
    return this.#current(held, [...answer.locations]);
  }

  /** The fallback delivery, for a client that cannot request findings for itself. */
  #publish(document: ModelDocument): void {
    if (!this.#publishOnChange) return;
    const service = this.#service;
    const schema = this.#inputs.schemaFor(document.text);
    // Silent on purpose: an absence already reported at startup should not be repeated on every
    // keystroke, and there is nothing here a user could act on that they were not already told.
    if (service === undefined || schema === undefined) return;
    const findings = service.findingsIn(document.text, schema);
    if (this.#documents.isSuperseded(document.uri, document.version)) return;
    this.#connection.sendDiagnostics(
      publishDiagnosticsFor(document.uri, document.version, findings, this.#lines(document)),
    );
  }

  // --- the four steps every handler shares ---

  /**
   * The document, an error for one this server does not serve, or nothing for one it is not
   * holding.
   *
   * The two absences are different answers: not serving a document is this server saying to ask
   * elsewhere, while not holding one the editor never opened is nothing to say at all.
   */
  #held(uri: string, request: string): ModelDocument | ResponseError<void> | undefined {
    if (!serves(this.#declared, uri)) return unsupported(this.#declaration, uri, request);
    const document = this.#documents.get(uri);
    if (document === undefined) {
      this.#connection.console.info(`${request}: ${uri} is not open, so there is nothing to read`);
    }
    return document;
  }

  #lines(document: ModelDocument): LineIndex {
    return new LineIndex(document.text, asPositionEncoding(document.encoding) ?? DEFAULT_ENCODING);
  }

  #current<T>(document: ModelDocument, answer: T): T | ResponseError<void> {
    return currentOrDropped(this.#documents, document.uri, document.version, answer);
  }

  /** No answer, with the reason on the record rather than in a shrug. */
  #nothing(request: string, reason: string): null {
    this.#connection.console.info(`${request}: ${reason}`);
    return null;
  }

  // --- the legend, which the service fills in as it names kinds ---

  async #registerSemanticTokens(): Promise<void> {
    this.#semanticRegistration?.dispose();
    this.#semanticRegistration = await this.#connection.client.register(
      SemanticTokensRegistrationType.type,
      { documentSelector: null, legend: protocolLegend(this.#legend), full: true },
    );
  }

  /**
   * The client's copy of the legend is behind, so it is replaced where the client allows it.
   *
   * A client that takes neither a new registration nor a refresh keeps the legend it was given at
   * `initialize`, and is told so rather than left to render indices it cannot resolve.
   */
  async #legendGrew(): Promise<void> {
    if (this.#dynamicSemanticTokens) {
      await this.#registerSemanticTokens();
    }
    if (this.#legendRefreshSupported) {
      await this.#connection.languages.semanticTokens.refresh();
      return;
    }
    if (!this.#dynamicSemanticTokens) {
      this.#connection.console.info(
        'the language service named a token kind this client was not given a legend entry for, ' +
          'and this client accepts neither a new registration nor a refresh',
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/** Whether this module was run as a program rather than imported by a test or a bundler. */
function startedDirectly(): boolean {
  const entry = process.argv[1];
  if (entry === undefined) return false;
  const here = fileURLToPath(import.meta.url);
  try {
    return realpathSync(resolve(entry)) === realpathSync(here);
  } catch {
    return resolve(entry) === here;
  }
}

export function start(options: ModelServerOptions = {}): void {
  new ModelServer(createConnection(ProposedFeatures.all), options).listen();
}

if (startedDirectly()) start();
