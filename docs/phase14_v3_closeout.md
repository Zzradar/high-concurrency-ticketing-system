# Phase14 v3 本地工程收尾

本次以 `84a0acd` 的干净 main 为基线，按用户批准补齐冷启动模型、统一新 smoke 判定，并进行增量复验。不修改前端、业务状态机、数据库迁移、资源池参数或正式阈值，不 push。最终执行结果见 [当前报告](../performance/experiments/phase14-capacity/report.md)。

## 已核实的冷启动图

依据 `frontend/src/main.ts`、`App.vue`、`auth/authState.ts`、`router.ts`、`pages/SeatSelectionPage.vue` 和两次独立浏览器记录。App mount 发起认证，路由初始导航也发起认证，两者并行。第一个成功更新用户状态的认证触发通知 watcher；App 认证完成回调再读取通知。路由认证完成后读取场次，然后并行读活动、座位布局与余票；三读完成并合并座位后，并行读取可恢复 checkout 和订单列表。

这里的冷启动指独立浏览器上下文、空客户端恢复状态，不表示后端缓存一定处于冷态。

因此正常已登录冷启动为 10 个 GET：auth/me ×2、notifications ×2、session/event/layout/availability 各1、checkout 列表1、订单列表1。checkout 查询使用 sessionId 和 recoverable=true，订单查询使用 sessionId 和 limit=20。两个认证响应谁先到达会改变通知与场次请求的实际交错，不能人为规定一条串行总顺序；实现保留源码的因果关系和并行关系。浏览器独立记录四组请求区间重叠，源码提供依赖边，负载测试使用真实 asyncRequest 复现。

认证、通知及列表用固定 startup_* 标签；路径标签采用模板，不含业务 ID、URL 查询参数或 Run ID。startup 统计完整一次性启动，page 继续统计原场次加三读的页面窗口，原延迟阈值保持原值。startup_availability 与持续 availability 分开；startup_auth 仍按原 auth 阈值产生诊断。

## 场景与身份

U1/U2/J1/S1 的每个首次进入身份执行一次完整冷启动。闭合模型使用原 onceState，开放模型使用原全局 iterationInTest 和边界上限；一次性启动不消耗额外身份，不改变 60/25/15 分组、思考时间、刷新速率或每人购买上限。共享的一秒非业务调度保护尾段保留，达到计划数后的 tick 仍在身份访问和 HTTP 之前退出。

O1 继续只有下单写链，H/E 不增加页面读取。L1/L2 在 releaseAtMs 写入之前，分别初始化 background、backgroundHold、backgroundOrder 实际会使用的全部不同身份；三个切片互不重叠，不碰无会话登录切片。初始化复用同一 k6 page 函数，每个切片单 VU 分批执行，原背景预热阶段和登录窗口随后按原曲线开始。启动原始样本、守恒结果和资源样本位于每轮独立 background-startup 目录，不合入登录窗口的延迟和吞吐。

v3 仅调整配置 version 并添加 pageStartup 描述；业务人数、窗口、切片边界、安全线和正式标准与 v2 完全相同。生成数据和快照写入 smoke-v3；旧数据目录与历史 Run ID 不变。startupPlan 与 startupDelivery 按用户总数和固定步骤计数逐项校验 planned=started=completed，任何缺失、dropped、中断或错误仍失败，两种模式共用标准。

## smoke 与正式判定

新 smoke 的 functional 检查功能、调度、分类、数据库正确性和证据完整性。capacity、overload_protection、formal_recovery 一律 not_applicable；不适用不是通过。measurement_validity 保留本地/小样本不能建立正式测量的说明。原恢复函数仍按正式连续窗口计算，结果放入 diagnostic.formalRecovery；L 对照保留实际 p95 倍率、样本数、吞吐和原阈值比较，顶层 status 为 not_applicable。采样开销比较也仅写入 diagnostic。

历史 verdict/recovery/comparison 不转换、不覆盖；报告引用时保留其原判定。孤立 pswpin 仍只降级 smoke 测量证据；换出、OOM、重启、正确性、系统错误、请求卡死、dropped 和原内存安全线规则没有放宽。正式容量模式仍使用原有性能判定和换页停止规则。

## 时钟采样修复与首次失败

新模型第一次 U2 被 invalid scheduling 停止：Docker CLI 启动包含在 SQL 时钟往返时间内，最后一次偏移估计 105.85ms，不确定范围 320.54ms，超过原 100ms 偏移线。保留该轮失败，不将其追认成功。主负载 70/70/70、dropped=0、数据库14项全局不变量均为0、12笔支付最终全部完成且 invalid=0；但支付探针被终止后，客户端终态计数不完整，原对账仍失败。

修复仅把 Docker/psql 建连放在计时之前，通过已建立的只读连接测量 SQL 时间，随后关闭精确所属连接；保留偏移、不确定范围和连接关闭证据，不调整100ms门槛。测试覆盖建连不进入计时、读失败仍关闭，以及正式/ smoke 的原保护规则。该修复后使用全新 Run ID 复验，不通过重复相同配置挑选成功结果。

## 可重复执行

```powershell
python -X utf8 -m unittest discover -s performance/tests
python -X utf8 performance/scripts/run_phase14.py prepare --smoke --yes
node performance/scripts/record_phase14_page_flow.mjs <独立证据目录>/browser.json
python -X utf8 performance/scripts/phase14_local_closeout.py
```

增量驱动依次执行两轮 U1、两轮 U2（第二轮双分片）、三档 J1、S1、L1/L2 各自对照和登录轮。每轮恢复快照、清空 Redis、生成新 Run ID；遇到失败立即保存并结束本次驱动，不自动重试。浏览器校准应在独立恢复后且没有压力运行时执行，脚本只关闭自己创建的浏览器和15174端口Vite，不加载 .env、不访问外网。

本次不机械重跑 O/H/E：其业务输入与 HTTP 写链未变化，原完整矩阵、H3 发车和 exporter 故障证据继续作为对应实现的本地功能证据，不能当作 v3 正式测量。新增 async 迭代等待由离线真实模块测试和受影响下单/认证集成回归覆盖。最终报告逐项区分本次执行与沿用记录。

## 三项独立结论

代码、测试和本地功能预演的完成情况由当前报告及新证据确定。正式万人容量验证仍需要隔离压力机与被测系统、资源与时钟资格证据，以及正式 G0；本机同宿主 smoke 不能替代。当前没有证据证明或否定万人容量。
