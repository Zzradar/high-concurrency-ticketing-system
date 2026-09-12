import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir:'./phase15-e2e',workers:1,fullyParallel:false,timeout:60000,
  reporter:[['list'],['json',{outputFile:'../performance/experiments/phase15-sales-window/playwright.json'}]],
  use:{actionTimeout:10000,baseURL:'http://127.0.0.1:5177',...devices['Desktop Chrome'],trace:'retain-on-failure'},
  webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5177 --strictPort',url:'http://127.0.0.1:5177/events',reuseExistingServer:false,
    env:{VITE_USE_MOCK_API:'false',VITE_API_PROXY_TARGET:'http://127.0.0.1:18095',VITE_STRIPE_PUBLISHABLE_KEY:''}},
})
