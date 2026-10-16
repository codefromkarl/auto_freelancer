# QQ Bot 通知与可选审批

QQ Bot 使用腾讯官方 AppID/AppSecret 和 `https://api.bot.qq.com`，通过 Gateway 出站连接接收好友和群聊事件。可以另选签名 HTTP 回调，但不要同时运行两个接收端。

## 本地配置

凭证放在项目根目录 `.env.qqbot`，该文件被 Git 忽略；权限设为 0600。变量示例只包含占位符：

```dotenv
QQ_BOT_APP_ID=你的AppID
QQ_BOT_APP_SECRET=你的AppSecret
QQ_BOT_API_BASE=https://api.bot.qq.com
QQ_BOT_TARGET_TYPE=c2c
QQ_BOT_TARGET_ID=
QQ_BOT_APPROVER_OPENIDS=
```

`TARGET_TYPE` 支持 `c2c` 私聊和 `group` 群聊。接收对象和审批者必须使用平台下发的 OpenID，不能填 QQ 号码。群审批者填写 `member_openid`，私聊填写 `user_openid`。允许多个审批者时用逗号分隔，空名单不授予任何人权限。

```bash
# 验证真实连接并退出
.venv/bin/python scripts/manual_pipeline/run_qqbot.py --once-ready
# 接收消息，不执行投标
.venv/bin/python scripts/manual_pipeline/run_qqbot.py
```

给机器人发送 `身份` 可取得当前聊天接收对象和发送者自己的 OpenID。由管理员写入配置后再发送 `候选`。这个过程不自动修改账号或将第一位发送者设为审批者。

## 候选与审批

本节适用于 `BID_APPROVAL_MODE=qq`。设置 `BID_APPROVAL_MODE=automatic` 后，机器人只发送执行结果，不需要批准命令，也不需要审批者名单；自动候选依据系统策略提交，信息不足自动暂缓。自动投标不依赖 Gateway 接收器，主动通知仍需要 AppID/AppSecret 和接收对象。

候选快照冻结项目版本、完整文案、本币报价、工期、账号和接收对象。消息包含有效期和内容版本：

```text
候选
批准风险 快照ID 内容版本
拒绝 快照ID 内容版本
```

普通 `批准` 不能放行未知客户/账号条件；`批准风险` 表示指定审批者已人工核对消息列出的未知资料。当前自动提交仍要求账号技能实时匹配、报价和工时限额、远端项目内容一致、内容校验与持久防重。缺失公开客户资料不等于客户可信。

候选消息同时显示竞标公开样本数量、中位价、本稿价差和建议补充的交付项。数据不足会明确提示人工核对，不等于低竞争。评估报告随最终内容冻结；新报价、新文案、过期或变化的竞标快照需要重新批准，旧版无评估记录不用于提交。

审批记录不自动开启投标。交易配置在现有 `.env` 中，默认：

```dotenv
BID_SUBMISSION_ENABLED=false
BID_APPROVAL_MODE=qq
BID_MAX_DAILY_ATTEMPTS=1
BID_MAX_DAILY_SCORED_PROJECTS=20
BID_MAX_AMOUNT_USD=1000
BID_MIN_NET_HOURLY_USD=15
BID_MAX_ESTIMATED_HOURS=40
```

这些是受控试运行上限，不是通用接单标准。`BID_MAX_DAILY_ATTEMPTS=0` 取消本地每日次数限制，仍统计尝试；平台额度、过期、内容校验与防重继续生效。操作者明确开启真实投标后设置 true 并启动 `scheduler.py --submit`。QQ 模式需内容批准；automatic 模式需有效系统决策、明确付款验证、当前完整评分和竞标评估、收益及账号资格通过。详细条件见 [自动投标计划](../plans/2026-10-12-automatic-bidding.md)。

## 运行方式与限制

- 调度器默认预览：抓取、单模型评分、准备候选并通知，不提交。未配置 QQ 接收对象时只保留本地候选，不假装送达。
- 接收器和调度器共享独立 `qqbot.db`；审批、事件去重、通知回执和每日用量不会依赖进程内存。
- 未启用真实投标时，QQ 批准只保存状态。启用后执行器每 5 秒检查已批准记录；过期记录必须重新准备，不能延长旧批准。
- 通知超时或响应不完整记为结果未知，不自动重发。用户可主动发送 `候选` 获取当前内容。
- QQ 主动消息受平台权限和额度限制；收到用户消息后可使用关联 `msg_id` 被动回复。鉴权成功、Gateway READY 不证明主动通知权限或实际送达。
- 真实账号凭证、QQ 对象和审批者尚未配置时，不启动无人值守交易。后台进程守护和公网部署需要独立执行与验收。

## 可选 HTTP 回调

```bash
.venv/bin/uvicorn qqbot_main:app --app-dir python_service --host 127.0.0.1 --port 8101
```

平台回调路径为 `/qqbot/callback`。普通事件必须通过 Ed25519 原始请求体签名和时间戳检查；注册挑战按官方协议应答并限制输入，避免成为任意报文签名接口。反向代理与公网地址需要另行配置，不能用 API Key 代替 QQ 事件验签。

官方来源：[鉴权接口](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html)、[腾讯官方 SDK](https://github.com/tencent-connect/qqbot-nodejs)。
