import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [
    // The React and Tailwind plugins are both required, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],

  build: {
    // Route splitting in src/app/App.tsx does most of the work. These manual
    // groups handle what it cannot: shared vendor code would otherwise be
    // duplicated into several route chunks or hoisted back into the entry.
    //
    // The split that matters is three: Three.js is ~450 KB on its own and is
    // needed by one section of one route, so it must never sit in the entry
    // chunk that a student loading /auth has to download.
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router'],
          three: ['three'],
          motion: ['gsap', 'motion'],
        },
      },
    },
    // The default 500 KB warning is noise once Three.js is deliberately isolated
    // in a lazily fetched chunk. Set just above it so a regression in any *other*
    // chunk still warns.
    chunkSizeWarningLimit: 600,
    // Source maps for a production bundle this size cost build time and disk on
    // a small VM, and nothing in the deploy consumes them.
    sourcemap: false,
  },
})
