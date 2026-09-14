/**
 * The one place this repository reaches the language service.
 *
 * Everything about EnergyPlus model text comes from `@idfkit/language`, and it
 * is reached at `@idfkit/idfkit/language`, the shared name's subpath, rather than by
 * the component's own package name. That is the pattern `@idfkit/idfkit/weather`
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

import type { LanguageService } from "./language-service.js";

/** The shared name's subpath. The only specifier this repository resolves. */
export const SUBPATH = "@idfkit/idfkit/language";

/** The component behind it, and the name a user can actually install today. */
export const COMPONENT = "@idfkit/language";

/** The shared install name, which is what the subpath above belongs to. */
export const SHARED_NAME = "@idfkit/idfkit";

/**
 * What this module says when nothing was installed to speak for itself.
 *
 * Distinct from the guard's message on purpose. The guard's message assumes the
 * shared name is present and only the optional component is missing; this one
 * covers the case where neither name resolves at all.
 *
 * It names the component rather than the shared name as what to install, which
 * is the one place this repository does not send a user to the shared name. It
 * cannot yet: `@idfkit/idfkit` has not been published to the npm registry, so
 * the instruction that reads best would be the instruction that fails. When it
 * is published this message goes back to asking for it.
 */
export const NOT_INSTALLED =
  "The model server answers about EnergyPlus model text through the idfkit language service, " +
  `and neither '${SUBPATH}' nor '${COMPONENT}' could be resolved here.\n` +
  "\n" +
  `    npm install ${COMPONENT}\n` +
  "\n" +
  `The shared install name, '${SHARED_NAME}', is the one this server prefers and is not on the ` +
  "npm registry yet: the registry refused the unscoped name 'idfkit', and the facade has not yet " +
  "been published under its scoped name. So install the component under its own name for now. " +
  "Until it is there this server answers nothing about model text and says so rather than " +
  "guessing. The Python server, which serves Python source, is unaffected.";

/** Node's codes for a specifier that resolved to nothing. */
const RESOLUTION_CODES: ReadonlySet<string> = new Set([
  "ERR_MODULE_NOT_FOUND",
  "MODULE_NOT_FOUND",
  "ERR_PACKAGE_PATH_NOT_EXPORTED",
]);

/**
 * The same condition without a code.
 *
 * A bundler or a test runner resolves imports itself and reports a failure in
 * its own words with no `code` at all. Measured under vitest 2.1.8, an absent
 * subpath arrives as a plain `Error` reading `Could not resolve
 * "<subpath>" imported by ...`. Matching on phrasing is weaker than
 * matching on a code, so it is used only in support of the specifier check
 * below, never on its own.
 */
const RESOLUTION_PHRASES: readonly string[] = [
  "Cannot find package",
  "Cannot find module",
  "Could not resolve",
  "Failed to resolve",
  "Failed to load url",
  "is not exported from package",
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
       * message is this module's. `'component'` means the component is
       * installed and threw on the way up, so the message carries its error
       * rather than an install instruction: telling someone to install what
       * they already have is the one thing that would not help them.
       *
       * This module never produces `'component'`. It re-throws that case, and
       * the caller decides whether an installed-but-broken component is worth
       * failing over. `main.ts` decides it is not.
       */
      readonly origin: "guard" | "resolver" | "component";
      readonly message: string;
    };

/** How a specifier is reached. Replaceable so a test can drive every branch. */
export type SubpathImport = (specifier: string) => Promise<unknown>;

const importSubpath: SubpathImport = (specifier) =>
  import(/* @vite-ignore */ specifier);

/**
 * The specifiers this module will resolve, in the order it prefers them.
 *
 * THE SHARED NAME COMES FIRST AND IS STILL THE INTENDED ONE. Reaching the component through the
 * shared name's subpath rather than through its own package name is what
 * `contracts/language-service-expected.md` fixes, and it is what gives a user one name to install
 * and the facade one place to say what is missing.
 *
 * THE SECOND ENTRY EXISTS BECAUSE THE FIRST CANNOT BE INSTALLED YET. `@idfkit/idfkit` is not on
 * the npm registry. The registry refused the unscoped name `idfkit` to its similarity filter, and
 * support confirmed on 2026-09-14 that no exception is possible, so the facade moved to the scoped
 * name; it has not been published under it yet, and the publish workflow's shared-name job does
 * not run on release. The scoped packages
 * ship on time and the shared name does not, which would leave this server unable to answer for a
 * reason that has nothing to do with either repository's code.
 *
 * So the component is accepted under its own name when the shared name is absent. This is a
 * fallback and not a second supported way in: nothing else in this repository names the component,
 * the guard's message still asks for the shared name where the shared name is what is missing, and
 * the day `@idfkit/idfkit` is published this array loses its second entry and nothing else changes.
 */
export const SPECIFIER_ORDER: readonly string[] = [SUBPATH, COMPONENT];

/** The six functions `contracts/language-service.md` fixes. */
const SURFACE = [
  "contextAt",
  "completionsAt",
  "explainAt",
  "declarationAt",
  "findingsIn",
  "position",
] as const;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function codeOf(error: unknown): string | undefined {
  const code: unknown = (error as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : undefined;
}

/** The names a failure has to mention before it is one of ours to translate. */
const SPECIFIERS: readonly string[] = [
  SUBPATH,
  COMPONENT,
  `'${SHARED_NAME}'`,
  `"${SHARED_NAME}"`,
];

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
  if (typeof module !== "object" || module === null) return false;
  const candidate = module as Record<string, unknown>;
  return SURFACE.every((name) => typeof candidate[name] === "function");
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
  // The first specifier that resolves wins. A specifier that resolves to nothing is not an answer
  // yet, because the next one may resolve; only the last failure is reported, and it is reported
  // in the terms the first specifier deserves, since the shared name is what a user should install.
  let unresolved: LanguageServiceLoad | undefined;
  for (const specifier of SPECIFIER_ORDER) {
    try {
      module = await load(specifier);
      unresolved = undefined;
      break;
    } catch (error) {
      if (isUnresolved(error)) {
        unresolved = { ok: false, origin: "resolver", message: NOT_INSTALLED };
        continue;
      }
      // The guard ran, which means the shared name is installed and the component is not. That is
      // a real answer from a real facade, and trying the component's own name after it would only
      // fail again in worse words.
      if (isGuardRefusal(error)) {
        return { ok: false, origin: "guard", message: messageOf(error) };
      }
      throw error;
    }
  }
  if (unresolved !== undefined) return unresolved;

  // Resolved, but not carrying what the contract fixes. That is a broken
  // install rather than an absent one, and it is still an absence: a server
  // that called into it would be calling undefined.
  if (!hasSurface(module)) {
    return {
      ok: false,
      origin: "resolver",
      message:
        `'${SUBPATH}' resolved, but does not carry the language service surface ` +
        `(${SURFACE.join(", ")}). Check that the installed ${COMPONENT} matches the idfkit ` +
        "it is a peer of; the two are released in lockstep.",
    };
  }

  return { ok: true, service: module };
}
