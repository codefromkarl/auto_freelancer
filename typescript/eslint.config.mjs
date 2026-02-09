import { defineConfig, globalIgnores } from 'eslint/config';
import eslintConfigNext from 'eslint-config-next';
import eslintPluginPrettierRecommended from 'eslint-plugin-prettier/recommended';

const eslintConfig = defineConfig([
  ...eslintConfigNext,
  // Prettier 配置 (禁用其他可能与 Prettier 冲突的规则)
  eslintPluginPrettierRecommended,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    // Additional ignores:
    'node_modules/**',
    '*.config.*',
    '.env*',
    'coverage/**',
  ]),
  // 覆盖规则以避免与 Prettier 冲突
  {
    rules: {
      // 允许未转义的 HTML 实体（在中文项目中常见）
      'react/no-unescaped-entities': 'off',
      // Prettier 处理格式化
      'prettier/prettier': 'warn',
    },
  },
]);

export default eslintConfig;
