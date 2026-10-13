import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'src-tauri/target', 'src-tauri/gen']),
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
      'react-refresh/only-export-components': 'off',
      // The block editor edits the parsed resume in place, as the Qt editor
      // does, so that keys it doesn't know keep their place in the file: the
      // document is a mutable object held across renders, not React state,
      // and a resume is JSON of any shape. (The React Compiler, which these
      // three rules prepare code for, isn't used.)
      'react-hooks/refs': 'off',
      'react-hooks/immutability': 'off',
      'react-hooks/globals': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
])
