import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { sites } from '@openai/sites-vite-plugin'

export default defineConfig({
  plugins: [vue(), sites()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'happy-dom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})

