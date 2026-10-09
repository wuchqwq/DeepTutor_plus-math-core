# 本轮 DeepSeek 配置：等待用户填写

2026-10-09：用户已确认新 key、费用授权及最小 localhost 无界面浏览器权限；按最新执行约定，由用户亲自填写凭据。执行任务仅查看了 tutor-demo `.venv` 顶层文件名，没有读取 `deepseek.key.dpapi` 或复制凭据。

## 用户所需动作

本任务原页面和 API 正在本机运行，`/settings` 与 `/health/ready` 均实际返回 HTTP 200。

1. 打开 [Connections](http://127.0.0.1:49300/settings/connections)，点 **Add connection**。
2. **Provider** 选 **DeepSeek**；**Base URL** 留空，使用项目登记的默认地址 `https://api.deepseek.com`；**API Key** 由用户自行填写新 key。保持密码框隐藏，无需向聊天发送值。
3. 在该连接的模型发现/LLM 字段选实际可用的 DeepSeek 型号，并启用 **LLM** 服务。不要使用启动占位标签 `deepseek-config-pending`。
4. 点 **Apply changes** 使配置生效；仅点 **Save draft** 不会生效。在 [LLM](http://127.0.0.1:49300/settings/llm) 确认该模型为默认模型。
5. 在 [Task models](http://127.0.0.1:49300/settings/task-models)，全局选 **Follow the chat model**，每个任务选 **Follow the global task model**，保证标题等后台调用也用同一模型。
6. 完成后只回复“已配置”及非敏感的实际模型名。执行任务随后只报告配置/连接验证成功或失败，不回显凭据。

该页面当前使用的标准配置位置为：

`C:\Users\13471\Documents\Codex\2026-10-09\task-2\DeepTutor_phase_d\data\phase-d-runtime\startup-integrated-S8\data\user\settings\model_catalog.json`

由现有设置页面维护此文件；不用手改 JSON，也不创建额外凭据框架。运行 home 的 `data/` 已忽略提交。

## 固定的非敏感运行设置

- 两版、alignment、selector、标题均使用同一实际 DeepSeek 型号；若为滚动别名，记录 UTC 和实际响应 model/id/created/system_fingerprint/usage。
- temperature=0，单 worker，并发=1。alignment 明确 top_p=1；其他调用使用原 provider 默认并记录实际 wire 参数。
- ordinary 输出上限 4096，alignment 2048，原 selector 1024。额外调用和 HTTP 重试如实计数。
- 8 场景已冻结；题目为实数 `x,y` 满足 `x²+xy+y²=3`，求 `Q=x²−xy+y²` 范围。具体输入见 `protocol.json`，不因失败换样本。
- 预计 39–47 次模型调用；本轮脚本建议合计 60 次请求的执行边界，与用户已授权的费用范围一致。当前付费调用=0、学生提交=0。
- 同题、同初始学生信息；两版独立 session/SQLite/episode。普通版不读取评审答案；集成版独享明确的人审数学 source，结论应称信息增强整体方案比较。
- 首轮保持原 teaching/presentation/publication；完成真实结果后停止，交 dot 独立审阅。

## 当前证据和阻塞

ordinary 与 integrated 原容器启动/关闭检查通过；两版原 API ready 检查通过；独立无界面 Chromium 实际打开原 `/chat`，HTTP 200 且输入框可见，有真实截图。浏览器组合固定为 Playwright 1.57.0 / Chromium 153.0.8010.12，版本不匹配如实保留。

这些只证明启动可用。真实 Provider、8 场景三维比较、S8 方法确认、教学回应和刷新 publication 回放均 **NOT_RUN**。当前阻塞是用户尚未完成本任务标准认证配置；不重复询问费用或是否新 key。

本次代码仅 evaluation 接线/观察/导出，原产品与数学 authority/publication 源码无修改。当前只有本地独立分支；尚无 draft PR。历史 closeout 测试为 PRIOR_REPORT_ONLY，Actions 为委托记录的 NOT_RUN_QUOTA，本任务未 dispatch。
