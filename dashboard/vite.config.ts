/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.split(path.sep).join('/')

          if (
            /\/node_modules\/(react|react-dom|scheduler|react-router|react-router-dom)\//.test(
              normalizedId,
            )
          ) {
            return 'vendor-react'
          }

          if (
            normalizedId.includes('/node_modules/recharts/') ||
            normalizedId.includes('/node_modules/victory-vendor/') ||
            normalizedId.includes('/node_modules/d3-') ||
            normalizedId.includes('/node_modules/lodash/')
          ) {
            return 'vendor-charts'
          }

          if (
            normalizedId.includes('/node_modules/@radix-ui/') ||
            normalizedId.includes('/node_modules/@floating-ui/')
          ) {
            return 'vendor-ui-primitives'
          }

          if (normalizedId.includes('/node_modules/lucide-react/')) {
            return 'vendor-icons'
          }

          if (
            normalizedId.includes('/node_modules/react-markdown/') ||
            normalizedId.includes('/node_modules/remark-') ||
            normalizedId.includes('/node_modules/micromark') ||
            normalizedId.includes('/node_modules/mdast-util') ||
            normalizedId.includes('/node_modules/unist-util') ||
            normalizedId.includes('/node_modules/hast-util')
          ) {
            return 'vendor-markdown'
          }
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
