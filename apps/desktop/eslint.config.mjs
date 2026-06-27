// @ts-check
import rootConfig from '../../eslint.config.mjs';

/**
 * Desktop package ESLint config. Extends the shared root config and points the
 * typed-linting project service at a tsconfig that includes the main, preload,
 * renderer, and test files (which live across multiple build tsconfigs).
 */
export default [
  ...rootConfig,
  {
    languageOptions: {
      parserOptions: {
        // Disable the auto-discovering project service in favour of one explicit
        // tsconfig that spans main, preload, renderer, and test files.
        projectService: false,
        project: ['./tsconfig.eslint.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
];
