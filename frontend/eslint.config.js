import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // eslint-plugin-react-hooks v7 ships new React-Compiler-aligned rules as
      // errors. This codebase hasn't adopted the Compiler, so treat its
      // *advisory* rules (cascading-render / ref-access heuristics) as warnings
      // rather than CI-blocking errors. The correctness rule (rules-of-hooks)
      // stays an error via the recommended set. Revisit if/when adopting the
      // React Compiler.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/refs': 'warn',
      // shadcn/ui intentionally co-locates variant helpers (e.g. buttonVariants)
      // with the component; this rule only affects Fast Refresh in dev, never
      // production output.
      'react-refresh/only-export-components': 'warn',
    },
  },
])
