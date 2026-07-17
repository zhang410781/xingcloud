import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
    plugins: [vue()],
    build: {
        chunkSizeWarningLimit: 900,
        rollupOptions: {
            output: {
                manualChunks(id) {
                    if (!id.includes('node_modules')) return
                    if (id.includes('@element-plus/icons-vue')) return 'element-plus-icons'
                    if (id.includes('element-plus')) return 'element-plus-core'
                    if (id.includes('echarts')) return 'echarts'
                    if (id.includes('@xterm')) return 'xterm'
                    if (id.includes('vue-router')) return 'vue-router'
                    if (id.includes('pinia')) return 'pinia'
                    if (id.includes('axios')) return 'axios'
                    if (id.includes('/vue/')) return 'vue'
                },
            },
        },
    },
    server: {
        host: '0.0.0.0',
        port: 3000,
        proxy: {
            '/api': {
                target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
            '/ws': {
                target: process.env.VITE_WS_PROXY_TARGET || 'ws://127.0.0.1:8000',
                ws: true,
            },
        },
    },
    resolve: {
        alias: {
            '@': '/src',
        },
    },
})
