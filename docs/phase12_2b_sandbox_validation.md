# Phase12-2B Stripe Sandbox 验收记录

## 1. 结论与证据裁决

日期：2026-09-09。Phase12-2B 按用户确认的一次性收尾授权完成，采用**分层证据**：
真实渠道处理中与前端可见状态已经验收；隐藏/失焦的精确请求调度由确定性自动化测试覆盖，
未把未观察到的真实浏览器时间线伪称为已观察。

真实渠道身份、一次退款、Webhook、库存与金融终态全部独立核验，不适用前端调度豁免。
真实前台GET无重叠且终态停止。浏览器工具创建另一标签后原页仍为visible，
受限DOM接口不暴露document.hasFocus，无法取得可信的系统级blur/hidden完整时间线。
这些操作属于观测限制，不能记作真实隐藏通过，也没有据此认定生产缺陷。

授权提示将调度断言归入39项定向测试；实际它们位于
`frontend/src/pages/OrderPage.refund.test.ts`（44项），已包含在同基线158项全量测试，
本轮又运行44项verbose专项全部通过。39项是支付恢复测试，不虚报其包含退款调度断言。
对应全部实质条件：真实B与E08的pending闭环、E05真实页面恢复、确定性调度断言、
无并行请求异常、新样本全部收敛及文档准确披露，满足本轮分层裁决。

当前不支持部分退款、退款失败后自动第二次退款、项目外 Dashboard 退款自动认领，
以及 succeeded → failed 后续冲正。Stripe Sandbox 不是生产资金或真实银行结算证明。
本记录不代表生产部署、真实3DS全量重跑、真实银行到账或容量/SLO验收。

## 2. 基线、环境和证据位置

验收基线为 `main@7e8ae617465fac4cd4991fea223496bbe5942e9e`，加五个此前获准补丁：
两个后端测试文件、OrderPage.test.ts、OrderPage.vue、OrderView.vue，共53新增、5删除。
提交前按换行归一化比较 `refresh-unlock-total.diff`，五个文件内容完全一致。
两个后端文件只修复故障注入同步时序和旧Order字段契约；生产后端不变。
前端清理过时支付Attempt，并修正刷新解锁守卫和提示条件。

本轮专用隔离Compose使用独立数据库卷和网络，后端/数据库/Redis健康；专用guard、
Stripe CLI与Vite按进程实际命令、创建时间、父子关系和目标复核。后端使用test Secret，
前端使用test Publishable Key、真实模式、隔离代理；新监听器签名密钥仅通过运行环境配置。
API为官方Stripe，币种cny，核验的PaymentIntent均livemode=false。没有Dashboard创建退款。

原始证据保留在仓库已有忽略目录 `backend/build/phase12-2b-validation/`，以下文件名均
相对该目录。完整对象身份仅用于忽略目录内的运行审计；本记录只列对象类型与缩略尾号。
这些本机证据不随Git发布；复核需保留该目录，不能仅凭本文代替原始日志。
`remaining-evidence-inventory.json`记录此前原始日志哈希，`one-pass-preflight.json`记录本轮预检。

## 3. 真实样本

全部退款金额58000分、cny，均核对本地身份及Stripe Retrieve/List。

| 样本 | 订单尾号 / Refund尾号 | 实际结果 | 原始证据 |
| --- | --- | --- | --- |
| A，E01 | 0ce627 / re_…HAPYqQ | 普通BUYER全额退款成功，重复请求复用 | sandbox-audit-a-after-refund.json；sandbox-local-a-terminal-repeat.json |
| B，E04 | d2e1e0 / re_…68x3n9 | Stripe pending→succeeded；处理中权益有效；并发重复202复用 | sandbox-audit-b-processing.json；sandbox-audit-b-later.json；sandbox-local-b-processing-repeat.json |
| C，E05 | 00115c / re_…xzCMoH | BUYER成功；真实空body、双击单POST、刷新与重新登录恢复；约4秒完成 | remaining-c-http-trace.jsonl；sandbox-audit-c-final-readonly.json；remaining-c-webhook.json |
| D，E06 | 5560b2 / re_…6PHr99 | 支付未被接纳，SYSTEM自动退款成功；订单/预订自然过期、座位释放 | remaining-d-payment-timeline.json；remaining-d-system-events.json；sandbox-audit-d-end.json |
| 新样本1，E07 | a3d410 / re_…VMc82E | 普通成功卡，退款约3秒完成；捕获真实提交禁用；完整BUYER闭环 | one-pass-card-check.json；one-pass-state-trace.jsonl；sandbox-audit-one-pass-first-final.json |
| 新样本2，E08 | dd5478 / re_…RqTCzH | 指定异步成功卡，本地接纳；真实pending约两分钟后BUYER成功 | sandbox-audit-second-processing.json；sandbox-audit-second-final.json；one-pass-second-state-trace.jsonl |

一次性授权后的新增订单总数为2，没有第三个。E07普通测试卡造成窗口不足，但资金与库存
已自然闭环，不是代码缺陷。E08使用正确异步成功测试方式，支付开始18:50:44.199，
本地接纳18:51:20.132，早于19:00:44.199处理截止；真实成功事件时间由one-pass-webhooks.json核对。
E07由用户在回复准备前自行完成支付，代理读取到PAID后没有再次启动支付。

较早E06的支付处理截止17:36:57.560，Stripe成功事件17:36:59，超过期限约2秒；
accepted_at为空，SYSTEM/PAYMENT_NOT_ACCEPTED自动退款于17:39:04.695完成。
这是人工准备与确认跨过已启动计时的样本失效，不伪称BUYER验收；没有对原Attempt重付。
最后查询隔离库PROCESSING退款数为0，新样本座位均已释放，不保留失效样本占座。

## 4. 真实前端与请求记录

使用同一Edge验收浏览器实际操作；新标签独立重新读取服务器状态，不假定与内置浏览器
共享页面内存。E05确认框显示整单¥580、无金额编辑；点击暂不退款后无POST，
本地与Stripe退款均为0，见remaining-cancel-http.json及sandbox-audit-c-cancel-current.json。

E05双击确认只产生一次空body POST。E07确认后实际DOM出现
“正在提交退款申请…”且disabled，之后进入PROCESSING；此前缺少的瞬时禁用证据得到补充。
E08双击亦只产生一次POST，bodyBytes=0、非chunked，202返回PROCESSING。
捕获方式为隔离后端网络命名空间内的限时被动观测，只持久化指定订单请求时间、长度、
响应状态；不保存认证头或原始正文，不注入或修改生产源码。

E08 UTC时间线（one-pass-second-http-snapshot.jsonl）：

| 时刻 | 观察 |
| --- | --- |
| 10:53:10.526062 | 单次无正文退款POST |
| 10:53:10.534265 | 202/PROCESSING响应 |
| 10:53:28.735949 → 10:53:28.736678 | GET/200，PAID/PROCESSING |
| 10:53:30.757864 → 10:53:30.759898 | 上次完成约2秒后下一次GET |
| 10:53:56.493、10:54:38.340 | 页面实际仍visible；后一次已尝试新建空白标签，不能当hidden |
| 10:55:17.698584 | 数据库终态完成，座位释放 |
| 10:55:17.879097 | 最后一次串行终态确认GET完成 |
| 至10:56:26.691170 | 无后续周期GET，终态停轮询 |

整段最大在途GET数为1。识别退款成功时源码追加一次串行Order确认，不是并行轮询。
汇总见one-pass-browser-summary.json。没有获得window blur及连续激活事件的真实精确时间线，
由第1节分层裁决处理，不把工具新建标签或人工提示当成焦点证据。

E05退款完成后整页刷新、退出/重新登录并直接打开订单URL，均恢复退款完成、订单取消、
座位释放。E08真实页面亦显示完成，无Stripe对象号、Webhook正文或原始渠道错误。
页面快照保留于本会话浏览器工具输出；辅助报告remaining-progress-report.md记录对应步骤。

## 5. Stripe、Webhook 与本地不变量

每笔BUYER退款按已接纳PaymentIntent核验Retrieve和List，List limit100、has_more=false、
完整身份匹配对象恰好1条；payment_intent、amount、currency及metadata.local_refund_id/order_id
一致。真实refund.created事件的request.idempotency_key等于本地Refund.id。
新增样本证据one-pass-webhooks.json，较早样本见sandbox-webhook-check*.json和remaining-c-webhook.json。
真实退款创建没有因为双击或Worker恢复形成第二笔资金动作。
真实List为单页；多页、starting_after和10页上限沿用Fake Stripe用例，没有制造大量真实退款。

CLI真实签名事件写入Inbox；退款Webhook仅唤醒对账，渠道终态须主动核实。
A/B各自有效签名重复投递两次均200且Inbox数量不变；缺签名、伪造签名、错误密钥均400，
Inbox和金融状态不变。此证据本轮沿用，没有反复重放；真实CLI事件与手工重复验签分开记录。

| 时点 | Refund / Order / Reservation / Seat | 通知 |
| --- | --- | --- |
| B、E07、E08 BUYER PROCESSING | PROCESSING / PAID / CONFIRMED / SOLD，指针NULL | REFUND_COMPLETED=0，权益有效 |
| BUYER成功瞬间 | SUCCEEDED / CANCELLED / CANCELLED / AVAILABLE，指针NULL | REFUND_COMPLETED=1，AUTO_REFUND_COMPLETED=0 |
| E06 SYSTEM成功 | SUCCEEDED；不改变仍在支付窗口内的票务权益，随后订单自然过期 | AUTO_REFUND_COMPLETED=1，非BUYER通知 |

BUYER完成时Order/Refund使用同一完成时间，通知dedupe_key为refund-terminal加本地Refund ID。
座位完成瞬间AVAILABLE并不意味着永久不可转售。全过程未手工修改金融/库存状态，未暂停Worker。

## 6. 自动化门禁：沿用与新执行

前述五个补丁与最后通过的总diff完全一致。以下沿用项在当前HEAD及对应最终补丁下通过，
没有把不同基线Phase11历史报告当作本轮结果；构建中生产后端未变。

| 范围 | 结果 | 原始日志 |
| --- | --- | --- |
| 崩溃同步目标连续5轮 | 5/5，含终态和唯一退款审计 | sync-fix-targeted-1.log至-5.log；sync-fix-targeted-audits.json |
| 买家退款 | 38/38 | sync-fix-phase12_buyer_refund_integration_test.py.log |
| Stripe支付/恢复；崩溃窗口 | 各11/11 | sync-fix-phase11_stripe_integration_test.py.log；sync-fix-phase11_crash_window_integration_test.py.log |
| 正常Dockerfile构建与CTest | 28/28 | sync-fix-build.log |
| Phase12迁移 | 4/4（沿用） | sync-fix-migration.log |
| Phase12源码契约 | 5/5（本轮补存原始输出） | one-pass-source.log |
| 指标源码；离线performance单测 | 4/4；102/102（本轮补存原始输出） | one-pass-metrics-source.log；one-pass-offline-performance.log |
| 模拟支付；订单生命周期 | 6/6；2/2 | sync-fix-payment_integration_test.py.log；sync-fix-order_lifecycle_integration_test.py.log |
| 基础HTTP；预订HTTP | 4/4；9/9 | sync-fix-http_integration_test.py.log；sync-fix-reservation_http_integration_test.py.log |
| Phase4目标/全套 | 1/1；6/6 | phase4-compat-targeted.log；phase4-compat-phase4_http_integration_test.py.log |
| 订单超时/并发 | 3/3；1/1 | phase4-compat-order_expiry_integration_test.py.log；phase4-compat-order_expiry_concurrency_test.py.log |
| Checkout HTTP/并发/恢复 | 6/6；4/4；2/2 | phase4-compat-checkout_session_*.py.log |
| Seat hold；认证；多客户端；支付失败 | 11/11；7/7；2/2；1/1 | phase4-compat对应套件日志及suite-results.jsonl |
| 指标smoke；Prometheus规则 | 3/3；4条 | phase4-compat-metrics-smoke.log；phase4-compat-metrics-check.json；sync-fix-promtool.log |
| 支付前端定向 | 39/39 | refresh-unlock-targeted.log |
| 前端全量 | 17文件158/158 | refresh-unlock-full.log |
| 类型检查与构建 | vue-tsc -b与Vite通过 | refresh-unlock-build.log |
| Mock Playwright | 10/10 | refresh-unlock-e2e.log |

数据库新卷001–009、seed及全部六份SQL verifier通过，sandbox-database-init.log。
较早门禁清理后六份通过，phase4-compat-final-sql.json；新增真实A/B后002–006通过，
sandbox-final-sql.json。初始化专用001硬编码seed总数，在新增样本后执行曾失败，
该失败保留，不能宣称真实退款后的六份全部通过。未删除真实样本来迎合seed断言。

本轮新执行：真实E07/E08、只读身份/不变量/请求审计；
`npm --prefix frontend test -- src/pages/OrderPage.refund.test.ts --reporter=verbose`
44/44，1.76秒，one-pass-refund-scheduling.log；文档链接、范围与敏感信息检查，git diff检查。
为将此前只在会话中的轻量离线输出独立落盘，另新执行Phase12源码5/5、指标源码4/4、
离线performance 102/102（分别0.049、0.042、0.630秒）。没有重跑全部工程门禁，
没有新增测试或修改断言。没有lint脚本，不声称lint通过。

专项明确通过：2000ms串行、不重叠、blur/hidden暂停6秒、在途请求结束后不重启，
恢复立即读取、focus-first与visibility-first两种次序合并、初始失焦不轮询、成功/失败停止。
早期崩溃同步、Phase4契约及旧支付状态失败日志保留；获准修复后结果单列，不抹除历史失败。

## 7. 正式文档与提交边界

[后端README](../backend/README.md)更新入口、运行配置与验证方法；
[前端README](../frontend/README.md)补真实模式与退款入口；
[产品需求](product_requirements.md)明确退款政策、权益与不支持边界；
[后端设计](backend_technical-design.md)补义务持久化、List恢复、身份/租约/锁序与原子终态；
[前端设计](frontend_technical_design.md)补无body、防重复、串行恢复与权威终态清理。
本记录集中存放验收结论，未将原始运行文件加入Git。

本地提交严格分三组：两个后端测试、三个前端文件、上述六份正式文档。
每组提交前核对暂存路径和cached diff空白；不amend/rebase/squash、不推送。
提交哈希以Git历史及最终交付为准，不向本文写入自引用提交哈希。
现场服务和卷保留供复核，运行日志及临时观测器不属于提交内容。
