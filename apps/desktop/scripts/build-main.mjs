// Bundles the Electron main and preload processes into self-contained CommonJS
// files. Bundling (rather than tsc file-by-file emit) is REQUIRED for the
// preload: with `sandbox: true`, the preload runs in a restricted context whose
// `require` cannot load arbitrary local modules, so any shared imports (e.g.
// ../shared/ipc-contract) must be inlined. `electron` is the only external.
import { build } from 'esbuild';

const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  sourcemap: true,
  external: ['electron'],
  logLevel: 'info',
};

await build({
  ...common,
  entryPoints: ['src/main/index.ts'],
  outfile: 'dist/main/index.js',
});

await build({
  ...common,
  entryPoints: ['src/preload/index.ts'],
  outfile: 'dist/preload/index.js',
});
