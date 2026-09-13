# Phase19：全局轮询治理与混合读写验证

Stage0 完成，正式协议已冻结于 `protocol-sha256.json`。尚未完成 Phase19，尚未修改前端生产轮询逻辑；正式 SUT 容量测试和浏览器 A/B 即将开始。

基线为 `2c680e78d532eace9e7f28862e7efb6ef2bdf4fb`。分支 `phase19/global-polling-mixed-load` 使用独立工作树。旧阶段证据未修改。

## 已核验的边界

- Release C++20 构建和完整 CTest 36 项通过；基线 Vitest 288 项/36 个文件通过，production build 通过。
- 基线 performance Python 262 项通过；新增工具的测试结果独立记录，不冒充原始基线数量。
- Phase15/16/17 OFF 与支付集成回归共 57 项；其他逐项结果见 `stage0/manifest.json`。
- Fake Provider 支付、崩溃、退款分别 11、11、38 项；双实例 1 项和退款 verifier 3 项通过。
- 本阶段 5000 用户/有效 Session、5 个场次×5000席夹具生成成功，14 项数据库不变量均为零。
- 100/250/500/1000 actual VU **发生器资格**通过，不能称为业务系统支持这些同时在线用户。
- 用户批准独立 4 GiB 发生器身份后，100/250/500/1000/2000 VU 重新资格全部通过；旧 2 GiB 结果保留。3000 VU 加余量预测超线，未执行。
- 协议工具 Python 全量 294 项通过，浏览器七场景短时诊断及支付/退款/提交终态诊断通过；短时诊断不是正式 60/91/30 秒 A/B。
- 10000/20000/30000 actual VU 内存评估 UNSAFE，未实际运行；详见 `scale-estimate/`。

## 已确认的口径修正

用户已确认保留准确基线：**事件策略 OFF，本地 Bulkhead 保持默认**。`TrafficControl::wrap/acquire` 与事件策略无关，Availability 默认上限 16；不能写成“所有保护关闭”。过载 503 单独记录，不计为吞吐成功。

`stage0/manifest.json` 是采集当时的历史快照，包含当时待确认事项；此处记录后续用户已作出的选择，不重写历史快照。

## 证据与未完成项

`inventory.json` 和 `POLLING_INVENTORY.md` 来自冻结 Git 对象；`stage0/` 是基线回归；`generator-calibration/` 是使用轻量 stub 的资格测试；`diagnostics/` 保留缺失测试上下文、缺失统计扩展、遗漏旧容器名和初次不完整资格采样。

`protocol/` 已冻结，发生器执行核心哈希逐点校验。正式运行拒绝协议漂移、未资格的资源身份或超出资格的 VU；后续变更协议必须重新冻结并整组重跑正式基线，不能拼接 A/B。

浏览器全局轮询 A/B、SUT actual VU、混合读写、传播延迟、5000 累计旅程、1000 人热点以及前端实现仍未交付。这里没有生产 SLA、Stripe 容量或最大吞吐结论。

协议冻结只表示可以开始正式测量，不得把本目录的 Stage0 检查点当作 Phase19 完成报告或独立复验交付。
