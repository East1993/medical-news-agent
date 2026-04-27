# 医疗器械行业每日新闻推送 Agent

这是一个可以每天自动运行的小项目：它会抓取国内权威新闻源中最近 24 小时的医疗器械行业信息，先用规则筛选，再用 MiniMax 总结成一份 Markdown 简报，最后推送到你的企业微信群机器人。

你不需要自己买服务器。项目放到 GitHub 后，GitHub Actions 会每天定时帮你运行。

## 每天什么时候推送

默认每天北京时间 17:10 推送。

新闻时间范围固定为：

```text
前一天 17:00 至 今天 17:00
```

例如今天是 `2026-04-27`，它会看：

```text
2026-04-26 17:00 至 2026-04-27 17:00
```

## 为什么 GitHub Actions 写的是 10 9 * * *

GitHub Actions 的定时任务使用 UTC 时间，不是北京时间。

北京时间 = UTC 时间 + 8 小时。

所以：

```text
UTC 09:10 = 北京时间 17:10
```

因此配置文件里写的是：

```yaml
cron: "10 9 * * *"
```

## 你需要准备什么

1. GitHub 账号：用来存放项目，并让 GitHub Actions 每天自动运行。
2. MiniMax 账号：用来生成新闻筛选和简报。
3. 企业微信群机器人：用来把简报发到群里。

## 如何获取 MiniMax API Key

1. 打开 MiniMax 控制台。
2. 找到 API Key 或密钥管理页面。
3. 新建一个 API Key。
4. 复制它，后面要填到 GitHub Secrets 的 `MINIMAX_API_KEY`。

注意：项目使用 MiniMax 的 OpenAI-compatible Chat Completions API，不需要 `OPENAI_API_KEY`。

默认 API 地址是：

```text
https://api.minimax.io/v1
```

如果你的国内账号无法调用，可以尝试：

```text
https://api.minimaxi.com/v1
```

默认模型名是：

```text
MiniMax-M2
```

模型名以 MiniMax 控制台实际可用模型名称为准。如果控制台显示的名字不同，请按控制台填写。

## 如何获取企业微信群机器人 Webhook

1. 打开企业微信群。
2. 点击群右上角的设置。
3. 找到“群机器人”。
4. 添加机器人。
5. 复制机器人 Webhook 地址。
6. 后面填到 GitHub Secrets 的 `WECOM_WEBHOOK`。

Webhook 很敏感，不要发给别人，也不要写进代码。

## 如何创建 GitHub 仓库

1. 打开 GitHub。
2. 点击右上角 `+`。
3. 点击 `New repository`。
4. 仓库名可以填：

```text
medical-news-agent
```

5. 选择 `Public` 或 `Private` 都可以。
6. 点击 `Create repository`。

## 如何上传这些项目文件

你需要把本项目里的文件上传到 GitHub 仓库根目录。

最终 GitHub 仓库里应该长这样：

```text
main.py
sources.yml
prompt.md
requirements.txt
README.md
.github/workflows/daily-news.yml
```

注意：`.github` 文件夹也要上传，它决定了每天自动运行。

## 如何配置 GitHub Secrets

进入你的 GitHub 仓库后：

1. 点击 `Settings`。
2. 左侧点击 `Secrets and variables`。
3. 点击 `Actions`。
4. 点击 `New repository secret`。
5. 一个一个添加下面这些 Secret。

需要添加：

```text
MINIMAX_API_KEY
MINIMAX_BASE_URL
MINIMAX_MODEL
WECOM_WEBHOOK
```

## GitHub Secrets 应该填什么

`MINIMAX_API_KEY`

填你的 MiniMax API Key。

`MINIMAX_BASE_URL`

优先填：

```text
https://api.minimax.io/v1
```

如果不通，可以改成：

```text
https://api.minimaxi.com/v1
```

`MINIMAX_MODEL`

默认可以填：

```text
MiniMax-M2
```

如果 MiniMax 控制台显示其他可用模型名，请填控制台里的模型名。

`WECOM_WEBHOOK`

填企业微信群机器人的完整 Webhook 地址。

## 如何手动运行测试

1. 打开 GitHub 仓库。
2. 点击上方 `Actions`。
3. 左侧点击 `Daily Medical Device News`。
4. 点击右侧 `Run workflow`。
5. 再点一次绿色按钮 `Run workflow`。

这会立刻运行一次，不用等到每天 17:10。

## 如何确认运行成功

运行成功时，你会看到：

1. GitHub Actions 里任务变成绿色对勾。
2. 企业微信群收到一条 Markdown 简报。
3. 如果当天没有高价值新闻，群里会收到“今日无符合条件的高价值医疗器械行业新闻。”

## 如何查看报错日志

1. 打开 GitHub 仓库。
2. 点击 `Actions`。
3. 点开失败的那次运行。
4. 点 `Run news agent`。
5. 展开日志，看红色或报错文字。

程序不会打印 MiniMax API Key，也不会打印完整企业微信 Webhook。

## 如何新增新闻源

打开 `sources.yml`，照着已有格式添加：

```yaml
- name: 某省公共资源交易中心
  type: webpage
  url: https://example.com/
  priority: high
  category: procurement
```

字段解释：

`name`：新闻源名字。

`type`：可以填 `rss` 或 `webpage`。

`url`：新闻列表页或 RSS 地址。

`priority`：优先级，建议填 `high`、`medium`、`low`。

`category`：来源类型，常用值有：

```text
regulator     药监、卫健、医保等监管来源
procurement   集采、招标、公共资源交易来源
government    政府网、政策来源
association   行业协会
media         权威媒体
industry      行业平台
```

如果某个网站没有 RSS，就用 `webpage`。

## 如何修改推送时间

打开 `.github/workflows/daily-news.yml`，修改：

```yaml
cron: "10 9 * * *"
```

记住 GitHub Actions 用的是 UTC 时间。

如果你想北京时间早上 8:30 推送：

```text
北京时间 08:30 - 8 小时 = UTC 00:30
```

就写：

```yaml
cron: "30 0 * * *"
```

## 这个项目会重点关注什么

重点品类：

1. AED 急救
2. 生命支持通用产品
3. 体检设备
4. 中医康复设备
5. IVD 检验设备
6. 五官科设备
7. AI 创新类医疗设备
8. 基层常用医疗设备
9. 县域医院设备配置
10. 民营医疗机构采购设备

重点方向：

1. 医疗器械注册审批
2. 创新医疗器械审批
3. 集采和挂网采购
4. 医保支付政策
5. 基层医疗补贴
6. 县域医疗能力建设
7. 医疗设备更新政策
8. 行业监管和质量抽检
9. 经销商、渠道商可关注的采购机会
10. AI 医疗器械落地场景

## 常见问题排查

### Q1：企业微信没有收到消息怎么办？

先检查 GitHub Secrets 里的 `WECOM_WEBHOOK` 是否完整。然后打开 Actions 日志，看是否有 `WeCom push failed`。如果 Webhook 填错、机器人被删除、群机器人权限变化，都可能收不到。

### Q2：MiniMax 报错怎么办？

检查三个 Secret：

```text
MINIMAX_API_KEY
MINIMAX_BASE_URL
MINIMAX_MODEL
```

最常见原因是模型名写错，或者账号所在环境需要使用 `https://api.minimaxi.com/v1`。

### Q3：GitHub Actions 为什么没有自动运行？

可能原因：

1. `.github/workflows/daily-news.yml` 没有上传到仓库。
2. 仓库的 Actions 被禁用了。
3. 定时任务不是立刻生效，GitHub 有时会延迟几分钟。
4. 免费 GitHub Actions 偶尔会有排队延迟。

### Q4：为什么推送时间不是北京时间？

GitHub Actions 的 cron 使用 UTC 时间。北京时间比 UTC 快 8 小时。默认 `10 9 * * *` 对应北京时间 17:10。

### Q5：新闻太少怎么办？

可以在 `sources.yml` 增加更多省市药监局、卫健委、医保局、公共资源交易中心、药械采购平台。第一版 MVP 用的是通用网页抓取，对有些网站可能抓不到完整发布时间，这是正常的。

### Q6：新闻不相关怎么办？

可以在 `main.py` 里调整关键词：

```python
MEDICAL_DEVICE_KEYWORDS
BUSINESS_VALUE_KEYWORDS
EXCLUDE_KEYWORDS
```

也可以在 `prompt.md` 里强化筛选要求。

### Q7：如何添加更多官方新闻源？

去目标官网找到“通知公告”“政策文件”“招标采购”“医疗器械”等列表页，把网址添加到 `sources.yml`。官方监管部门和集采平台建议设置：

```yaml
priority: high
category: regulator
```

或：

```yaml
priority: high
category: procurement
```

### Q8：如何临时关闭每日推送？

最简单方法：

1. 打开 `.github/workflows/daily-news.yml`。
2. 在 `schedule` 前面加 `#` 注释掉。
3. 提交到 GitHub。

也可以进入 GitHub 仓库的 `Actions` 设置，临时禁用 workflow。

## 本地运行方式，可选

如果你电脑会用命令行，也可以本地测试：

```bash
pip install -r requirements.txt
python main.py
```

本地运行前需要先设置环境变量。代码小白可以优先用 GitHub Actions 测试，不必本地运行。

## 安全提醒

不要把下面这些信息写进代码：

```text
MINIMAX_API_KEY
WECOM_WEBHOOK
```

本项目通过 GitHub Secrets 读取它们，代码里不会写死敏感信息。
