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
 * `service.ts` holds the one import of `idfkit/language`. Everything here comes from `idfkit`
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
 * WHY THERE IS NO PROSE
 *
 * A prose pool is loaded by whoever wants prose in their offers, and this server loads none yet.
 * The contract's rule is that offers then carry no prose, not that this repository supplies some.
 */

import type {
  ClassifiedRegion,
  IdfDocument,
  ProsePool,
  Schema,
} from './language-service.js';
import type { CallerInputs } from './main.js';

/** The subpaths this module resolves. Both are the shared name's, never a component's own. */
export const CORE_SUBPATH = 'idfkit';
export const NODE_SUBPATH = 'idfkit/node';

/**
 * What this module says when the library is not installed.
 *
 * Distinct from `service.ts`'s message, which is about the optional language service. This one is
 * about the shared name itself, which is a different install and a different sentence.
 */
export const CORE_NOT_INSTALLED =
  `The model server resolves schemas, parses models and classifies text through '${CORE_SUBPATH}', ` +
  'and that could not be resolved here.\n' +
  '\n' +
  `    npm install ${CORE_SUBPATH}\n` +
  '\n' +
  'Until it is installed this server answers nothing about model text and says so rather than ' +
  'guessing. The Python server, which serves Python source, is unaffected.';

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

const importSubpath: Importer = (specifier) => import(/* @vite-ignore */ specifier);

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
  let core: CoreSurface;
  let node: NodeSurface;
  try {
    core = (await load(CORE_SUBPATH)) as CoreSurface;
    node = (await load(NODE_SUBPATH)) as NodeSurface;
  } catch (error: unknown) {
    const stated = error instanceof Error ? error.message : String(error);
    return { ok: false, message: `${CORE_NOT_INSTALLED}\n\nThe resolver said: ${stated}` };
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
      return undefined;
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
    const declared = core.getIdfVersion(text);
    if (declared === undefined || bundle.loaded(declared) !== undefined) return;
    requested.add(declared);
    try {
      await bundle.load(declared);
    } catch {
      // Left unresolved on purpose. See above.
    }
  }

  return { ok: true, inputs, warm };
}
