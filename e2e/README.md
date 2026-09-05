# Phase 10A-3 浏览器 E2E Smoke

E2E（端到端测试）独立放在仓库根目录，不改变前端依赖或生产后端路径。测试使用 Playwright Chromium 驱动真实浏览器，通过 Vite 同源 `/api` 代理访问 Performance Backend，并在真实 PostgreSQL 中核对终态；它不是容量测试。

## 前置条件与运行

从仓库根目录生成全新的 smoke 数据并确保支付模拟固定成功：

```powershell
python performance/scripts/reset_environment.py --profile smoke --yes
$env:TICKETING_PAYMENT_FORCE_OUTCOME = "SUCCESS"
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml up -d --force-recreate --wait backend
Set-Location e2e
npm ci
npx playwright install chromium
npm test
```

Playwright 自行启动 Vite，设置 `VITE_USE_MOCK_API=false` 和 `VITE_API_PROXY_TARGET=http://127.0.0.1:18080`。普通前端开发未设置该变量时仍代理到 `http://localhost:8080`。

## 覆盖范围

- `checkout-smoke`：真实 UI 登录、浏览活动与场次、选座、Checkout 和订单页。
- `payment-smoke`：API 安排待支付订单，浏览器观察 PROCESSING（处理中）并轮询到 PAID。
- `order-deeplink`：新的已认证上下文直接访问订单深链并刷新恢复。
- `multi-client`：两个独立 BrowserContext（浏览器上下文）使用两个真实认证 Session，同步同一 Checkout、订单和支付终态。

API 只负责 Arrange（安排前置数据），核心 Act（用户操作）由浏览器完成；断言同时覆盖用户可见结果和数据库事实。第一版固定 `workers=1`，避免共享 smoke 座位产生测试间竞争。

`e2e/.auth/`、依赖、HTML 报告和失败产物均被 Git 忽略。认证 `storageState`（浏览器认证状态）当前仅保存在内存；若将来落盘，也必须留在 `.auth/`，因为其中可能包含敏感 Cookie。失败时保留 trace 和截图，可在 `playwright-report/` 查看 HTML 报告。
