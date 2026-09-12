# Phase17 独立验收修复门禁

2026-09-12，原实施 worktree `high-concurrency-ticketing-system-phase17`，起点 `6c3d3994226f524fe44dde0522dee497203f5c7a`。首次fetch确认本地=远端、工作树clean。全部改动追加提交；未改写原六提交，未修改main、旧Phase16或detached review worktree。

## 五项 Major 的修复

|问题|根因与修复|新回归|
|---|---|---|
|金额静默改写|Number乘100再round接受非法精度；改为原始字符串+BigInt拆分，正安全整数分，固定两位回显|adminMoney、编辑页无请求测试；浏览器非法值0次写入，1/1.5/0.01/MAX_SAFE整数分落库和再次保存一致|
|旧空白Zone升级失败|旧NOT NULL允许空白，新名称约束拒绝；012保留原始身份映射，先保留非空白名称，再稳定分配最小可用后缀|空串/空格/制表换行等、多Venue、名称碰撞、普通名字/顺序/ID不变、注入失败整体回滚、fresh|
|salesWindow损坏RouterView|API仅类型声明、EventCard直接访问缺失窗口；入口runtime契约校验，TicketApiError进入可恢复页面，组件/工具安全显示不可用|列表/详情缺失、空对象、非法日期、非法日历、空区间与正常数据；浏览器错误页→退出→登录→重试恢复|
|退出异常跳过导航|请求finally清空用户但向外抛出，App await后的清理/router未执行；改为confirmed结果、401视为完成、其他错误提示，replace导航，保持initialized并使在途/me失效|success/401/timeout/network×活动/管理页；URL=route=/login，currentUser=null，登录表单可见，无刷新重新登录，退出后/me请求0|
|活动数量硬编码|固定2与实际空列表矛盾；由loading/events生成数量|loading/0/1/多场/重新加载的同步渲染|

消费者文案范围：EventListView介绍与城市品牌、App两侧页脚、OrderSummary“预订信息”、SelectedSeats整单失败提示、SeatGrid提交结果提示、OrderView演示到期提示。LoginView仅开发或明确Demo环境展示演示凭据（真实生产不显示），模拟支付/演示模式提示保留。Vue消费者页面检索 PostgreSQL、Redis、服务端、事务、MVP、Phase、SLA、高并发、SHANGHAI 无残留。

## 隔离环境与命令

专用网络 `p17-fix-net`，容器 `p17-fix-build/api/pg/redis`；PG16临时数据卷、Redis7.4，本轮数据库为postgres，后端localhost:18219，Vite localhost:5189。未复用已有环境。测试后四容器均停止，Playwright自行关闭Vite。临时配置、测试数据库口令和运行二进制不提交。

构建容器使用 `phase14-engineering-build:20260910-v3` 工具链，只读挂载本实施源码到/work；Drogon源码路径指向镜像预置版本：

```sh
cmake -S /work/backend -B /fix-build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=OFF -DTICKETING_FETCH_DROGON=ON -DFETCHCONTENT_SOURCE_DIR_DROGON=/src/build/_deps/drogon-src
cmake --build /fix-build -j 6
ctest --test-dir /fix-build --output-on-failure
```

实际编译标志 `-O3 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic`。DB按001–012、demo seed、phase16_seed.sql初始化；后者只是关键回归夹具，不是重新执行5000席性能测试。临时配置PG/Redis分别指向新容器，允许origin5189/5173，simulation failure_rate=0。

在仓库根目录设置 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`、`PHASE17_BASE_URL=http://127.0.0.1:18219`、`PHASE17_POSTGRES_CONTAINER=p17-fix-pg`、`PHASE17_REDIS_CONTAINER=p17-fix-redis`；Phase16 BASE_URL/POSTGRES_CONTAINER/PG_CONTAINER/REDIS_CONTAINER对应相同本轮隔离资源。实际执行：

```powershell
python backend/tests/phase17_schema_test.py
python backend/tests/phase17_venue_test.py
python backend/tests/phase17_publishing_test.py
python backend/tests/phase17_verifier_test.py
python backend/tests/phase16_migration_test.py
python backend/tests/phase16_read_model_test.py
python backend/tests/phase16_api_test.py
npm --prefix frontend run test -- --run
npm --prefix frontend run build
# 在frontend目录
npx playwright test --config playwright.phase17-fixes.config.ts
# 在仓库根目录
git diff --check
```

27项只读不变量：调用 `phase17_verify.QUERIES` 的13项和 `performance/verification/verify.sql` 的14项，将结果写本目录verifier.json；没有调用默认会写旧阶段路径的verify()。本结果不冒称重跑嵌套Phase15/16完整verifier。

## 准确结果

|门禁|结果|输出|
|---|---:|---|
|Release C++20 build / CTest|成功 /34 passed|cmake-configure.txt、cpp-build.txt、ctest.txt|
|完整Vitest|30文件、259 passed|vitest.txt|
|production build|通过|frontend-build.txt|
|Schema（含011升级和fresh）|8 passed|schema.txt|
|Venue / Publish|4 /9 passed|venue.txt、publish.txt|
|Phase16 PG / Redis Lua / HTTP|5 /11 /7 passed|phase16-pg.txt、phase16-lua.txt、phase16-http.txt|
|负例verifier / 只读不变量|3 passed /27项全0|verifier-negative.txt、verifier.json|
|真实Playwright|13 passed、0 flaky/skipped/failed|browser.txt、playwright.json、browser-evidence.json|
|diff检查|通过|提交前及提交后检查|

浏览器证据保留URL、Router、currentUser、logout状态、控制台错误、重新登录结果和价格落库值。pageerror数组全部为空，无未处理rejection或组件树错误；console仍记录匿名/auth/me的预期401及注入的401/ERR_FAILED，不能将其称作“控制台完全无错误”。超时通过拦截请求延迟8500ms触发真实Axios8000ms超时，网络失败通过route.abort；success使用真实后端200。以window标记验证没有document刷新。

初次production build发现新增测试fixture缺少类型必填字段，补全后完整Vitest和production build通过；未通过断言、跳过测试或强转unknown绕过。最后浏览器运行35.4s（精确毫秒见JSON）。新Playwright JSON去掉继承的webServer.env；txt仅规范化行尾空白，测试结果与时间不改。保留紧凑日志/结构化证据，无大体积二进制、trace、cookie、token或运行配置。

## 性能证据审计与未重跑范围

见[正式座位图优化证据审计](../../../docs/seat_read_optimization_evidence_audit.md)。已核对Phase10B、16、17正式文档及原始JSON，新表区分完整Seat、全场Availability、Layout、Zone Snapshot和Delta。分阶段核心证据已存在，因此不重复性能负载。跨阶段payload/Zone数不一致、Phase17旧镜像无固定构建SHA仍为明确证据限制，不计算提升比例。

未重跑Phase11/12全部支付退款、Phase14 G0/U1/U2、Phase16完整故障矩阵和Phase17全量规模测试：本轮改动不涉及支付后端、读模型协议或容量调参，关键迁移/发布/Zone回归已通过。旧证据目录及migration001–011的Git diff为空。用户5173现场已停止，不推测其当时代理或后端版本。
