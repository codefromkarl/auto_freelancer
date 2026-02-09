# Freelancer 官方 API 参考

> 本目录包含 Freelancer.com 官方 API 的参考文档。

## 目录

| 文档 | 说明 |
|------|------|
| [FREELANCER_API.md](./FREELANCER_API.md) | Freelancer 官方 API 端点完整参考 |
| [SDK_WRAPPER.md](./SDK_WRAPPER.md) | Python SDK 封装方法说明 |

## 官方资源

| 资源 | 链接 |
|------|------|
| API 文档首页 | https://developers.freelancer.com/docs |
| Postman 集合 | https://www.postman.com/freelancer-api |
| API 变更日志 | https://developers.freelancer.com/changelog |

## 快速链接

### 核心 API

- **Projects**: 项目搜索、详情、投标 https://developers.freelancer.com/docs/projects
- **Bids**: 投标管理 https://developers.freelancer.com/docs/bids
- **Milestones**: 里程碑支付 https://developers.freelancer.com/docs/milestones
- **Messages**: 消息通信 https://developers.freelancer.com/docs/messages
- **Users**: 用户信息 https://developers.freelancer.com/docs/users

### 认证

- OAuth 2.0 认证: https://developers.freelancer.com/docs/oauth-2-0
- API Token: https://developers.freelancer.com/docs/api-tokens

## SDK 使用

```python
from freelancersdk.session import Session
from freelancersdk.resources.projects import search_projects

# 初始化会话
session = Session(
    oauth_token="your_oauth_token",
    url="https://www.freelancer.com"
)

# 搜索项目
result = search_projects(
    session,
    query="python",
    search_filter={"min_avg_price": 100},
    limit=10
)
```

## 速率限制

| 级别 | 限制 |
|------|------|
| 免费用户 | 1000 次/小时 |
| 付费用户 | 10000 次/小时 |

详细信息请参考: https://developers.freelancer.com/docs/rate-limits
