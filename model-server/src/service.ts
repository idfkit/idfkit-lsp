/**
 * The one place this repository reaches the language service.
 *
 * Everything about EnergyPlus model text comes from `@idfkit/language`, and it
 * is reached at `idfkit/language`, the shared name's subpath, rather than by
 * the component's own package name. That is the pattern `idfkit/weather`
 * already ships: the shared-name package declares the component as an optional
 * peer, exposes it at a subpath, and guards that subpath with a dynamic import
 * that turns a missing package into a message naming what to install.
 *
 * Because the guard is a dynamic import behind a top-level await, this module
 * is asynchronous and the subpath cannot be required. The API behind it stays
 * synchronous: every function on `LanguageService` returns a value, so no
 * handler ever awaits an answer. Only startup awaits, and only once.
 *
 * THE GUARD'S WORDS ARE THE GUARD'S. When the shared name is installed and the
 * component is not, the facade throws a message that already names the install,
 * says why the component is optional, and says what still works without it.
 * This module reports that message unchanged. Rewording it would replace a
 * message written where the facts are known with one written where they are
 * not, which can only make it worse.
 */

import type { LanguageService } from './language-service.js';

/** The shared name's subpath. The only specifier this repository resolves. */
export const SUBPATH = 'idfkit/language';

/** The component behind it, which only the facade's guard names. */
export const COMPONENT = '@idfkit/language';

/**
 * What this module says when nothing was installed to speak for itself.
 *
 * Distinct from the guard's message on purpose. The guard's message assumes the
 * shared name is present and only the optional component is missing; this one
 * covers the case where neither is, which is the case in a checkout of this
 * repository today, because this repository does not install either.
 */
export const NOT_INSTALLED =
  `The model server answers about EnergyPlus model text through '${SUBPATH}', ` +
  'and that subpath could not be resolved here.\n' +
  '\n' +
  `    npm install idfkit ${COMPONENT}\n` +
  '\n' +
  `${COMPONENT} is an optional peer of idfkit, so installing idfkit alone leaves it out on ` +
  'purpose. Until both are installed this server answers nothing about model text and says so ' +
  'rather than guessing. The Python server, which serves Python source, is unaffected.';

/** Node's codes for a specifier that resolved to nothing. */
const RESOLUTION_CODES: ReadonlySet<string> = new Set([
  'ERR_MODULE_NOT_FOUND',
  'MODULE_NOT_FOUND',
  'ERR_PACKAGE_PATH_NOT_EXPORTED',
]);

/**
 * The same condition without a code.
 *
 * A bundler or a test runner resolves imports itself and reports a failure in
 * its own words with no `code` at all. Measured under vitest 2.1.8, an absent
 * `idfkit/language` arrives as a plain `Error` reading `Could not resolve
 * "idfkit/language" imported by ...`. Matching on phrasing is weaker than
 * matching on a code, so it is used only in support of the specifier check
 * below, never on its own.
 */
const RESOLUTION_PHRASES: readonly string[] = [
  'Cannot find package',
  'Cannot find module',
  'Could not resolve',
  'Failed to resolve',
  'Failed to load url',
  'is not exported from package',
];

/** The service, or why it could not be reached. */
export type LanguageServiceLoad =
  | { readonly ok: true; readonly service: LanguageService }
  | {
      readonly ok: false;
      /**
       * Whose words `message` is.
       *
       * `'guard'` means the facade ran and refused, and `message` is its own,
       * verbatim. `'resolver'` means nothing was installed to run, so the
       * message is this module's.
       */
      readonly origin: 'guard' | 'resolver';
      readonly message: string;
    };

/** How the subpath is reached. Replaceable so a test can drive every branch. */
export type SubpathImport = () => Promise<unknown>;

const importSubpath: SubpathImport = () => import(SUBPATH);

/** The six functions `contracts/language-service.md` fixes. */
const SURFACE = [
  'contextAt',
  'completionsAt',
  'explainAt',
  'declarationAt',
  'findingsIn',
  'position',
] as const;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function codeOf(error: unknown): string | undefined {
  const code: unknown = (error as { code?: unknown } | null)?.code;
  return typeof code === 'string' ? code : undefined;
}

/** The names a failure has to mention before it is one of ours to translate. */
const SPECIFIERS: readonly string[] = [SUBPATH, COMPONENT, "'idfkit'", '"idfkit"'];

/**
 * The subpath resolved to nothing, so no guard ran.
 *
 * Checked before the guard, because a bundler that fails to resolve the
 * component reports it in its own words and those words name the component too.
 * Shape first, then who is named, keeps the two apart.
 */
function isUnresolved(error: unknown): boolean {
  const message = messageOf(error);
  if (!SPECIFIERS.some((name) => message.includes(name))) return false;
  const code = codeOf(error);
  if (code !== undefined) return RESOLUTION_CODES.has(code);
  return RESOLUTION_PHRASES.some((phrase) => message.includes(phrase));
}

/**
 * The facade's guard ran and refused.
 *
 * Only the guard names the scoped component in a message that is not a
 * resolution failure: a failure to resolve the subpath names the shared name,
 * because the shared name is what depends on the component. So a message
 * carrying the component's name and none of the shapes above is the guard's,
 * and it is the message to report.
 */
function isGuardRefusal(error: unknown): boolean {
  return messageOf(error).includes(COMPONENT);
}

function hasSurface(module: unknown): module is LanguageService {
  if (typeof module !== 'object' || module === null) return false;
  const candidate = module as Record<string, unknown>;
  return SURFACE.every((name) => typeof candidate[name] === 'function');
}

/**
 * Reach the language service, or say why it could not be reached.
 *
 * Never throws for an absent component, which is the whole point: an absence is
 * a message the user can act on, not a crash that takes the server with it. Any
 * other failure is re-thrown exactly as it arrived, because an error from
 * inside a component that is installed is not a reason to tell someone to
 * install it.
 */
export async function loadLanguageService(
  load: SubpathImport = importSubpath,
): Promise<LanguageServiceLoad> {
  let module: unknown;
  try {
    module = await load();
  } catch (error) {
    if (isUnresolved(error)) {
      return { ok: false, origin: 'resolver', message: NOT_INSTALLED };
    }
    if (isGuardRefusal(error)) {
      return { ok: false, origin: 'guard', message: messageOf(error) };
    }
    throw error;
  }

  // Resolved, but not carrying what the contract fixes. That is a broken
  // install rather than an absent one, and it is still an absence: a server
  // that called into it would be calling undefined.
  if (!hasSurface(module)) {
    return {
      ok: false,
      origin: 'resolver',
      message:
        `'${SUBPATH}' resolved, but does not carry the language service surface ` +
        `(${SURFACE.join(', ')}). Check that the installed ${COMPONENT} matches the idfkit ` +
        'it is a peer of; the two are released in lockstep.',
    };
  }

  return { ok: true, service: module };
}
