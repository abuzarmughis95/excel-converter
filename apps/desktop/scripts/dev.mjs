// Dev orchestration with live reload:
//  1. build the Electron main + preload once (esbuild),
//  2. start the Vite dev server (HMR for the renderer),
//  3. launch Electron pointed at the Vite URL.
//
// Edits to renderer source hot-reload instantly. Edits to main/preload require
// a restart of this script (they are native processes, not HMR-able).
import { spawn } from 'node:child_process';
import { createServer } from 'vite';
import electronPath from 'electron';

const VITE_PORT = 5173;

async function main() {
  // 1. Build main + preload bundles.
  await runNode('scripts/build-main.mjs');
  await runNode('scripts/write-cjs-marker.mjs');

  // 2. Start Vite dev server.
  const server = await createServer({ configFile: 'vite.config.ts' });
  await server.listen(VITE_PORT);
  const url = `http://localhost:${VITE_PORT}`;
  server.config.logger.info(`\n  Vite dev server: ${url}\n`);

  // 3. Launch Electron against the dev URL.
  // ELECTRON_RUN_AS_NODE must be ABSENT (not empty) or Electron runs as plain
  // Node and `app` is undefined — so delete it from the child env entirely.
  const childEnv = { ...process.env, ELECTRON_RENDERER_URL: url };
  delete childEnv.ELECTRON_RUN_AS_NODE;
  const electron = spawn(electronPath, ['.'], { stdio: 'inherit', env: childEnv });

  const shutdown = async () => {
    electron.kill();
    await server.close();
    process.exit(0);
  };
  electron.on('close', shutdown);
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

function runNode(script) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script], { stdio: 'inherit' });
    child.on('close', (code) =>
      code === 0 ? resolve() : reject(new Error(`${script} exited ${code}`)),
    );
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
