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
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  // Guard: prevent production code from importing placeholder hooks.
  // Placeholder hooks (src/test/placeholders/) are only for T01 test setup.
  // T06 and T07 will delete them when real implementations land.
  // Files inside src/test/ and *.test.ts files are exempted — they ARE allowed
  // to import placeholders. Production .ts/.tsx files must not.
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/test/**', 'src/**/*.test.ts', 'src/**/*.test.tsx'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/test/placeholders/**', '../test/placeholders/**', '../../test/placeholders/**'],
              message:
                'Placeholder hooks are test-only. Import from src/features/.../hooks/ instead. ' +
                'If the real hook does not exist yet, this import is not allowed outside src/test/.',
            },
          ],
        },
      ],
    },
  },
])
