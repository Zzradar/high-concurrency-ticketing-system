import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir:'./phase16-e2e',workers:1,fullyParallel:false,timeout:90000,
  reporter:[['list'],['json',{outputFile:'../performance/experiments/phase16-availability/playwright.json'}]],
  use:{actionTimeout:10000,baseURL:'http://127.0.0.1:5176',...devices['Desktop Chrome'],trace:'retain-on-failure'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5176 --strictPort',url:'http://127.0.0.1:5176/events',reuseExistingServer:false,
    env:{VITE_USE_MOCK_API:'false',VITE_API_PROXY_TARGET:'http://127.0.0.1:18096',VITE_STRIPE_PUBLISHABLE_KEY:''}},
})
