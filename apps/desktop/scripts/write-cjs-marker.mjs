// Writes a CommonJS package marker into dist/ so Node/Electron treat the
// compiled main and preload (.js, emitted as CommonJS by tsc) as CJS, even
// though the workspace package.json declares "type": "module" for the ESM
// renderer toolchain. The renderer bundle is loaded by the browser as ESM and
// is unaffected by this Node-level marker.
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const distDir = path.resolve(import.meta.dirname, '..', 'dist');
await mkdir(distDir, { recursive: true });
await writeFile(path.join(distDir, 'package.json'), `${JSON.stringify({ type: 'commonjs' }, null, 2)}\n`);
