import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Served by the account backend at /app/ (see platform/accounts/uishell.py): absolute /app/ asset paths, no inline code.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
  server: { proxy: { '/v1': 'http://127.0.0.1:18800', '/auth': 'http://127.0.0.1:18800', '/readyz': 'http://127.0.0.1:18800' } },
  test: { environment: 'jsdom', globals: true },
});
