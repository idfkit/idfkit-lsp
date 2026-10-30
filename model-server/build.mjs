/**
 * Bundle the model server.
 *
 * A script rather than an esbuild command line for one reason: the level of each library compiled
 * into the bundle has to be read from that library's installed manifest at build time, and a command
 * line cannot do that on every platform this repository builds on. Once compiled in, a library has
 * no manifest beside it at run time, so `idfkit-lsp/versions` can only answer what this script
 * recorded.
 *
 * A checkout builds with a linked source map, which is how a debugger attached to the server finds
 * it. The two paths that ship the bundle pass `--sourcemap=external`, because neither ships the map
 * and a comment naming it would point at nothing.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const here = dirname(fileURLToPath(import.meta.url));

/** Resolved from `node_modules` at run time, so `levelOf` reads each one's manifest there. */
const EXTERNAL_SCOPE = '@idfkit/';

/** Stated in the `build` script, where `tools/check_declaration.py` holds it against the floor. */
const target = process.argv.find((arg) => arg.startsWith('--target='))?.slice('--target='.length);
if (target === undefined) throw new Error('build.mjs needs --target=<esbuild target>');

function readManifest(path) {
  return JSON.parse(readFileSync(path, 'utf-8'));
}

// The two sections `versionReport` names libraries from, so every name it reports is covered.
const manifest = readManifest(join(here, 'package.json'));
const declared = Object.keys({ ...manifest.dependencies, ...manifest.peerDependencies });
const compiledIn = declared.filter((name) => !name.startsWith(EXTERNAL_SCOPE));

const outfile = 'dist/main.js';

const result = await build({
  absWorkingDir: here,
  entryPoints: ['src/main.ts'],
  bundle: true,
  outfile,
  format: 'esm',
  platform: 'node',
  target,
  external: [`${EXTERNAL_SCOPE}*`],
  banner: {
    js: "import { createRequire as __nodeCreateRequire } from 'node:module'; const require = __nodeCreateRequire(import.meta.url);",
  },
  sourcemap: process.argv.includes('--sourcemap=external') ? 'external' : 'linked',
  metafile: true,
  logLevel: 'info',
  define: {
    // JSON text rather than an object: esbuild injects an object-valued define as a module of its
    // own, with a call to initialize it in every wrapped module of the bundle.
    __BUNDLED_LEVELS__: JSON.stringify(
      JSON.stringify(
        Object.fromEntries(
          compiledIn.map((name) => [
            name,
            readManifest(join(here, 'node_modules', name, 'package.json')).version,
          ]),
        ),
      ),
    ),
  },
});

// A declared library the bundle does not contain did not run, so no level may be stated for it.
// Read from the output rather than from `metafile.inputs`, which also lists a library imported and
// then tree-shaken away entirely.
const inputs = Object.keys(result.metafile.outputs[outfile].inputs);
for (const name of compiledIn) {
  if (!inputs.some((input) => input.startsWith(`node_modules/${name}/`))) {
    throw new Error(`${name} is declared and is not in the bundle, so its level would be false`);
  }
}
