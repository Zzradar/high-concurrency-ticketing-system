# Phase15 验证证据

- `integration/`：Phase16合并main时的门禁证据，基线d1d1fd7。
- `ctest.log`：最终32项CTest原始输出；`vitest.log`/`frontend-build.log`：前端最终日志。
- `external-gates.json`与`phase15_*_test.log`：migration、read、Reservation、Checkout、真实进程退出恢复、指标/查询计数，共20项真实外部门禁。
- `playwright.json`与`paid-after-end.png`：3条真实浏览器流程。
- `payment-refund-regression.log`：原Phase11 Stripe、crash-window、Phase12 BuyerRefund共60项；首轮59通过，1项因独立容器遗漏stdbuf行缓冲等待INFO日志超时。未更改生产退款逻辑或原测试断言。
- `refund-fence-recheck.log`：恢复原Phase12的`stdbuf -oL`启动方式后，该唯一失败项通过；按项合并结果为60/60。
- `verifier.json`与`phase16-regression/verifier.json`：Phase15检查及原Phase16/verify.sql检查，全部零违规；包含5060个已初始化Redis座位。
- `comparison.json`：从原Phase14模型的主shard原始HTTP点计算的六轮对比。
- `comparison/{baseline,current}/{g0,u1,u2}/`：原始压缩点、原Phase14 correctness/smoke结果、PostgreSQL差量和manifest。未纳入身份凭据、环境变量、认证cookies或生成数据文件。
- `gates.json`：最终门禁索引和精确计数。

## 重现

独立工作树保留Phase15 API（18095）、migration-only PostgreSQL、Phase12仿真（18115/18116）的运行数据。外部测试以固定的`phase15-api-postgres`、`phase15-redis`、`phase15-api-backend`为目标；不能对生产环境运行。

```powershell
python backend/tests/phase15_migration_test.py
python backend/tests/phase15_read_api_test.py
python backend/tests/phase15_reservation_test.py
python backend/tests/phase15_checkout_test.py
python backend/tests/phase15_crash_recovery_test.py
python backend/tests/phase15_observation_test.py
python backend/tests/phase15_payment_regression.py
python performance/verification/phase15_verify.py
npm --prefix frontend test
npm --prefix frontend run build
```

Playwright用`frontend/playwright.phase15.config.ts`；启动器仅在子进程环境传入既有测试账号口令PHASE15_TEST_PASSWORD，不将其写入报告。

原Phase16 API测试支持PHASE16_BASE_URL、PHASE16_POSTGRES_CONTAINER、PHASE16_REDIS_CONTAINER，以便把相同断言运行于本轮专用环境。默认目标保持不变。

性能采用已记录的baseline/current专用镜像与原Phase14 smoke目标：`python performance/scripts/run_phase15_comparison.py baseline`/`current`。必须保留或重新构建正确二进制镜像；每轮数据按已校验快照恢复。它使用新项目名称、私有端口18097/19097和独立生成目录，不使用已有Phase14项目。结束时仅stop当前对比项目，不删除其他容器或卷。

`summarize_phase15.py`从原始点重新计算percentile；request/s分母为首末HTTP响应跨度。Gate queryid来自该轮数据库实例，随restore可能不同，记录在对应gate-query-ids.json。实际运行二进制/镜像指纹见gates.json。性能仅为同机短负载工程对比，不能解释为生产容量或SLA。
