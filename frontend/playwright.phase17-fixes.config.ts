import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
 testDir:'./phase17-e2e',testMatch:'fixes.spec.ts',workers:1,fullyParallel:false,timeout:60000,
 reporter:[['list'],['json',{outputFile:'../performance/experiments/phase17-review-fixes/playwright.json'}]],
 use:{baseURL:'http://127.0.0.1:5189',...devices['Desktop Chrome'],trace:'off',actionTimeout:12000},
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5189 --strictPort',url:'http://127.0.0.1:5189/events',reuseExistingServer:false,
 env:{VITE_USE_MOCK_API:'false',VITE_API_PROXY_TARGET:process.env.PHASE17_FIX_API_TARGET || 'http://127.0.0.1:18219',VITE_STRIPE_PUBLISHABLE_KEY:''}}
})
