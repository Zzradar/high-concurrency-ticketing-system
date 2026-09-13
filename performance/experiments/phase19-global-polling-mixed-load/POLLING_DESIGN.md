# 全局网络轮询治理设计（实现前）

当前状态：本文件记录已审阅的实现约束。前端生产源码仍为 Phase18 准确基线；只有重新冻结协议后的完整 Stage2 基线结束，才应用实现。验收测试位于 frontend/tests/phase19.*，当前刻意暴露基线缺陷，不能记为通过。

## 复用边界

Availability 与 Admission 已有串行、游标、可见性和错误退避，不重写其状态管理。共享 pollingPolicy 保留普通轮询的 500–30000ms 范围，并修正 Retry-After 被截断至 30 秒的问题：有效服务器最短等待可超过普通退避上限，但不得超过 JavaScript 安全定时上限。超过可执行上限或非法数值不转换成溢出的极速定时器。不同业务可指定基础周期与退避上限。

新增 SingleFlight 小工具按业务身份共享在途读取；身份变化时先等待旧请求排空，再检查新生命周期是否仍有效。旧响应不允许更新新用户、订单或 Checkout。调用者处理错误和业务终态，工具不承担业务状态机或统一固定周期。

## 通知

匿名不请求。登录状态 watcher 负责立即读取，挂载时的 refreshMe 不再另起一次通知读取。通知基础周期 30 秒，ID/readAt 等稳定签名连续不变退避至 60 秒。面板、业务信号、focus/visible 与在途读取合并；一次页面激活短窗口内的延迟业务信号也合并，防止页面自己的权威同步再次触发相同通知请求。明确后续用户动作可立即刷新。

hidden 清除待执行定时器；在途允许结束但不得继续后台链。退出点击立即使通知生命周期失效，authState.logout 在等待网络前清除本地身份，其他页面同时停止用户相关轮询。通知错误不抛出未处理拒绝，也不破坏导航。

## 支付、退款和未知提交

订单 GET 继续串行共享。PaymentAttempt 与 Checkout GET 共用相同的单在途规则，轮询、手动刷新和恢复激活不得分别请求。每次 await 后核对页面、身份和业务代次，路由离开或身份变化时终止旧更新。

支付与 SUBMITTING 保留 15 秒墙钟期限。hidden 停止新请求；若期限在隐藏期间经过，恢复只允许一次最终权威读取，仍处理中则提示手动恢复。Retry-After 超过剩余期限时等待到期限直接结束自动恢复，不再请求，也不重置计时。终态立即清除定时器。退款仅 PROCESSING 才继续，使用 createRefund.pollAfterMs，错误退避并遵守 Retry-After。

salesWindow、OrderSummary 的本地倒计时继续更新，不纳入网络请求削减。测试应证明本地秒级显示仍变化而 HTTP 不随之增加。

## 验证

fake timers、固定 RNG、可控延迟 Promise 验证单在途、身份隔离、两个 visibility/focus 顺序、长 Retry-After、隐藏跨期限及终态。完整既有组件测试和 TypeScript production build 必须通过。随后使用同一冻结协议运行七场景 60s visible / 91s hidden / 30s restored 浏览器 A/B，以实际 XHR/fetch 发起时间和原生 visibility 判断，不替换 document.hidden 或浏览器定时器。
