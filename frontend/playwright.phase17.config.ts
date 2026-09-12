import {defineConfig,devices} from '@playwright/test'
export default defineConfig({testDir:'./phase17-e2e',workers:1,fullyParallel:false,timeout:90000,
 reporter:[['list'],['json',{outputFile:'../performance/experiments/phase17-admin-publishing/playwright.json'}]],
 use:{baseURL:'http://127.0.0.1:5177',...devices['Desktop Chrome'],trace:'retain-on-failure',actionTimeout:12000},
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5177 --strictPort',url:'http://127.0.0.1:5177/events',reuseExistingServer:false,
 env:{VITE_USE_MOCK_API:'false',VITE_API_PROXY_TARGET:'http://127.0.0.1:18117',VITE_STRIPE_PUBLISHABLE_KEY:''}}})
