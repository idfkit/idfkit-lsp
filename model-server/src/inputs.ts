/**
 * The four inputs the language service takes but does not produce.
 *
 * `main.ts` defines `CallerInputs` and states why they are the caller's: feature 005 fixes the five
 * answers as pure functions of text and schema, so resolving the schema, parsing the model, loading
 * the prose and asking the syntax layer to classify all fall to whoever calls. This module is where
 * that resolution lands. No handler changes because of it, which was the point of the seam.
 *
 * WHY THIS IS NOT IN `service.ts`
 *
 * `service.ts` holds the one import of `@idfkit/idfkit/language`. Everything here comes from `@idfkit/idfkit`
 * itself: `scanIdf` and `classify` from the syntax layer, `parseIdf` from the reader, and the
 * schema bundle from the library's Node edge. Naming `classify` inside the language service's
 * module would give a reader two names for one function, so the two imports stay apart.
 *
 * WHY THE SCHEMA ARRIVES LATE
 *
 * `CallerInputs.schemaFor` is synchronous, because every answer downstream of it is. The library's
 * schema loading is not: it reads from disk. `SchemaBundle` is built for exactly this and says so,
 * offering `load` for the asynchronous fetch and `loaded` for the synchronous question of whether a
 * version is already in hand. So the first request that names an unseen version is answered with
 * "no schema", the load is started, and the caller is told when it finishes. That is a real answer
 * and not a placeholder: at that instant no schema had been resolved, which is the third of the
 * three absences the contract requires this repository to carry without flattening.
 *
 * WHY PROSE IS LOADED HERE AND NOT REACHED FOR
 *
 * The schema's explanatory sentences are indexed by the slim schema and held in a separate pool,
 * off the parse path, because most callers never want them. An editor is the caller that does.
 * The pool is loaded on the same terms as a schema, for the same reason: reading it is
 * asynchronous and every answer that uses it is synchronous, so it is loaded when a document
 * arrives and read when a request is answered. One pool serves every version, so it is loaded once.
 */

import type {
  ClassifiedRegion,
  IdfDocument,
  ProsePool,
  Schema,
} from "./language-service.js";
import type { CallerInputs } from "./main.js";

/**
 * The specifiers this module resolves, each with the fallback it accepts.
 *
 * The shared name is preferred and is the one a user should install. It is not on the npm registry
 * today: the registry refused the unscoped name `idfkit`, and the facade has not yet been published
 * as `@idfkit/idfkit`, so the component's own name is accepted after it. `service.ts` carries the
 * same pair and the same reason for the language service; both lose their fallback on the day
 * `@idfkit/idfkit` is published.
 *
 * The shared name's `index.js` and `node.js` are plain re-exports of exactly these two, so the
 * fallback resolves the same code and not a substitute for it.
 */
export const CORE_SUBPATH = "@idfkit/idfkit";
export const CORE_FALLBACK = "@idfkit/core";
export const NODE_SUBPATH = "@idfkit/idfkit/node";
export const NODE_FALLBACK = "@idfkit/core/node";

/**
 * What this module says when the library is not installed.
 *
 * Distinct from `service.ts`'s message, which is about the optional language service. This one is
 * about the shared name itself, which is a different install and a different sentence.
 */
export const CORE_NOT_INSTALLED =
  "The model server resolves schemas, parses models and classifies text through idfkit, and " +
  `neither '${CORE_SUBPATH}' nor '${CORE_FALLBACK}' could be resolved here.\n` +
  "\n" +
  `    npm install ${CORE_FALLBACK}\n` +
  "\n" +
  `The shared install name, '${CORE_SUBPATH}', is the one this server prefers and is not on the ` +
  "npm registry yet: the registry refused the unscoped name 'idfkit', and the facade has not yet " +
  "been published under its scoped name. So install the package under its own name for now. Until it is there this server " +
  "answers nothing about model text and says so rather than guessing. The Python server, which " +
  "serves Python source, is unaffected.";

/** The members of the library this module calls, and nothing more. */
interface CoreSurface {
  scanIdf(text: string): object;
  classify(layer: object): Iterable<ClassifiedRegion>;
  parseIdf(
    text: string,
    schema: Schema,
    options?: { strict?: boolean },
  ): { document: IdfDocument };
  getIdfVersion(text: string): string | undefined;
}

/** The Node edge's bundle, in the two members this module uses. */
interface SchemaBundleSurface {
  load(version: string): Promise<unknown>;
  loaded(version: string): Schema | undefined;
  latest(): Promise<string>;
  /** The explanatory prose the manifests index into. One pool, not one per version. */
  loadProse(): Promise<ProsePool>;
  /** The pool if it has been loaded, or nothing. Synchronous, which is why it is usable here. */
  prose(): ProsePool | undefined;
}

interface NodeSurface {
  schemas(): SchemaBundleSurface;
}

/**
 * Either the resolved inputs, or why they could not be resolved.
 *
 * `warm` is the asynchronous half of `schemaFor`. Loading a schema reads from disk, and every
 * answer downstream is synchronous, so the two cannot be the same call. A caller that knows a
 * document has arrived awaits this before any request about that document can be asked, which is
 * what turns "no schema yet" from the usual answer into the rare one.
 */
export type InputsLoad =
  | { readonly ok: true; readonly inputs: CallerInputs; readonly warm: Warm }
  | { readonly ok: false; readonly message: string };

/** Resolve whatever this text needs, so the synchronous inputs have it in hand. */
export type Warm = (text: string) => Promise<void>;

type Importer = (specifier: string) => Promise<unknown>;

const importSubpath: Importer = (specifier) =>
  import(/* @vite-ignore */ specifier);

/**
 * Called when a schema that was not in hand has finished loading.
 *
 * The request that provoked the load has already been answered, truthfully, with "no schema". This
 * is how the wiring learns there is now something to answer from, so it can offer again. Without
 * it a document opened before its version was ever loaded would stay unanswered until the next
 * keystroke, which reads as a broken server rather than as a warm cache.
 */
export type SchemaArrived = (version: string) => void;

/**
 * Resolve the four inputs from the installed library.
 *
 * Both subpaths are imported dynamically and their failure is reported rather than thrown, for the
 * same reason `service.ts` does it: an install without the library must produce a message naming
 * what to install, not a stack trace at startup.
 */
export async function loadInputs(
  onSchemaArrived: SchemaArrived = () => {},
  load: Importer = importSubpath,
): Promise<InputsLoad> {
  /** The first specifier that resolves, or the last failure, reported in the shared name's terms. */
  async function resolve<T>(preferred: string, fallback: string): Promise<T> {
    try {
      return (await load(preferred)) as T;
    } catch {
      return (await load(fallback)) as T;
    }
  }

  let core: CoreSurface;
  let node: NodeSurface;
  try {
    core = await resolve<CoreSurface>(CORE_SUBPATH, CORE_FALLBACK);
    node = await resolve<NodeSurface>(NODE_SUBPATH, NODE_FALLBACK);
  } catch (error: unknown) {
    const stated = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      message: `${CORE_NOT_INSTALLED}\n\nThe resolver said: ${stated}`,
    };
  }

  const bundle = node.schemas();
  // One entry per version a load has been started for, so a version whose load is in flight or has
  // already failed is not asked for again on every keystroke.
  const requested = new Set<string>();

  function schemaFor(text: string): Schema | undefined {
    const declared = core.getIdfVersion(text);
    if (declared === undefined) {
      // The version cannot be determined from the text. The contract calls this its own kind of
      // absence, and guessing a version here would mis-map every positional field in the file.
      return undefined;
    }
    const held = bundle.loaded(declared);
    if (held !== undefined) return held;
    if (!requested.has(declared)) {
      requested.add(declared);
      void bundle
        .load(declared)
        .then(() => onSchemaArrived(declared))
        .catch(() => {
          // A version the bundle cannot serve stays unresolved, which is the answer already given.
        });
    }
    return undefined;
  }

  const inputs: CallerInputs = {
    schemaFor,

    classify(text: string): readonly ClassifiedRegion[] | undefined {
      // `Token` is `Region & { kind }`, which is `ClassifiedRegion`. Nothing is computed here; the
      // generator is drained because the protocol payload needs a length before it needs a token.
      return [...core.classify(core.scanIdf(text))];
    },

    documentFor(text: string): IdfDocument | undefined {
      const schema = schemaFor(text);
      if (schema === undefined) return undefined;
      try {
        // Not strict. Strict parsing throws on the first diagnostic, and the text this server is
        // handed is an editor's buffer: a half-typed statement with no terminator yet is the
        // normal state of a file being worked on, not a file that cannot be read. The findings
        // that parsing produces reach the editor as diagnostics through `findingsIn`, so
        // collecting them here rather than throwing loses nothing and keeps the declarations of
        // every statement that did parse available while a later one is still being written.
        return core.parseIdf(text, schema, { strict: false }).document;
      } catch {
        // Text too broken for even a lenient read is text with no declarations to report, which
        // the handler states as an absence rather than filling in.
        return undefined;
      }
    },

    proseFor(): ProsePool | undefined {
      // Whatever has been loaded, and nothing where nothing has. An explanation without prose
      // reports the absence; it is never filled in from the field's name.
      return bundle.prose();
    },
  };

  /**
   * Load the schema this text declares, if it is not already in hand.
   *
   * Awaited by the caller on the notification that a document arrived or changed, so the requests
   * that follow find a loaded bundle. A version the bundle cannot serve resolves here rather than
   * rejecting: that is not an error to report, it is `schemaFor` continuing to say no schema,
   * which is one of the three absences the contract requires this repository to carry.
   */
  async function warm(text: string): Promise<void> {
    // The pool is version-independent and idempotent to ask for, so it is requested alongside the
    // first schema rather than on a path of its own. A failure to read it leaves prose absent,
    // which is a state every answer already carries; it is not a reason to fail the schema too.
    const withProse =
      bundle.prose() === undefined
        ? bundle.loadProse().catch(() => undefined)
        : undefined;

    const declared = core.getIdfVersion(text);
    if (declared !== undefined && bundle.loaded(declared) === undefined) {
      requested.add(declared);
      try {
        await bundle.load(declared);
      } catch {
        // Left unresolved on purpose. See above.
      }
    }
    await withProse;
  }

  return { ok: true, inputs, warm };
}
