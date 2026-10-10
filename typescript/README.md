# BidMaster 管理界面

Next.js 管理界面通过 `lib/api.ts` 访问 FastAPI，业务 API 统一发送 `X-API-Key`。

## 启动

```bash
npm ci --ignore-scripts
npm run dev
```

先按照 `../docs/getting-started/STARTUP_GUIDE.md` 配置并启动后端，然后在 `/settings` 保存 API Base URL（默认 `http://localhost:8000/api/v1`）和 API Key。保存后每次请求读取当前配置，不将密钥写入客户端构建环境变量。

## 验证

需要 Node.js 22.18 或更高版本以运行 TypeScript 契约测试。

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

测试只使用模拟 HTTP 响应，覆盖鉴权头、筛选字段、报价币种、消息字段映射、未知提交不重试和未实现功能报错。

## 能力边界

- 项目列表、详情、评分、投标、提案、模板配置和消息对接现有后端接口。
- Web 的单项目/批量评分使用规则评分；Python 并发流水线使用 LLM 评分，二者目前仍是不同算法。
- 项目标记、归档、国家/名称技能筛选、Excel 导出、竞争者分析和后台全量评分暂未接入。调用返回明确错误，不报告任务成功。
- CSV/JSON 导出使用实际分页项目数据。同步请求被接受不等于抓取完成。
- 消息与提案页面不再用虚构记录作为默认或错误回退；风控页、历史趋势图仍为明确标注的演示数据。
- 提案统计反映本地状态，不能替代平台中标、交付或收款证据。

本轮验收见 `../docs/plans/2026-10-10-reliability.md`。
