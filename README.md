# 每日远程岗位智能匹配推送 (daily-job-digest)

每天自动抓取远程岗位，用 DeepSeek 按你的技能画像打分匹配，把 Top 30 以邮件推送到你邮箱。

**数据源**：RemoteOK (JSON API) + We Work Remotely (RSS) + Hacker News "Who is Hiring" (Algolia API) + Jobicy / Remotive（无 Key 免费聚合 API）。所有来源可由 `ENABLED_SOURCES` 裁剪；请求自动支持"代理失败→直连"重试。

**工作流**：并行抓取近24h新岗位 → 跨来源去重 → 过滤已推送历史 → DeepSeek 分批打分 → 按分数排序取 Top N → 发送 HTML 邮件

**前置条件**：Python 3.9+（建议 3.10）；一个 DeepSeek API Key（https://platform.deepseek.com）；任意支持 SMTP 的邮箱（QQ/163/Gmail 等）。**不绑定任何职业背景**——换用户只需改自己的技能画像 `skill_profile.txt` 与搜索标签即可。

---

## 一、快速开始

```powershell
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 一键初始化向导：生成 config.env + skill_profile.txt，并引导填写账号信息
#    （已有文件不会被覆盖；Windows/Linux/macOS 通用）
python scripts/setup.py

# 3. 打开 skill_profile.txt，删除示例占位行，填写你的【真实】背景
#    （年限/职业路径/技术栈/优势/偏好 —— 这是 DeepSeek 打分的唯一依据）

# 4. 试跑一次（不真发邮件，只生成 HTML 预览，预览在 logs/ 下）
python daily_job_digest.py --dry-run

# 5. 正式推送一次 / 配置每天自动推送（见“三、定时任务”）
python daily_job_digest.py
```

> 不用向导也可以手动初始化：`copy config.env.example config.env`（Linux/macOS 用 `cp`）后编辑，
> 再 `copy skill_profile.txt.example skill_profile.txt` 参考示例填写。

## 二、配置说明

配置文件为项目根目录的 `config.env`（从 `config.env.example` 复制）。所有敏感信息只放这里，不要提交到版本库。配置优先级：**系统环境变量 > config.env > 内置默认值**。

| 配置项 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key，必填 |
| `DEEPSEEK_API_URL` / `DEEPSEEK_MODEL` | DeepSeek 接口地址与模型，一般不用改 |
| `DEEPSEEK_BATCH_SIZE` | 每批打分数量（默认15，省钱可调大，稳定可调小） |
| `DEEPSEEK_MAX_RETRIES` | 打分失败重试次数 |
| `SMTP_HOST` / `SMTP_PORT` | SMTP 服务器（465端口走SSL，其余走STARTTLS） |
| `SMTP_USER` / `SMTP_PASS` | 发件邮箱与授权码（**不是登录密码**） |
| `MAIL_TO` | 收件人，多个用英文逗号分隔 |
| `MAIL_SENDER_NAME` | 发件人显示名称 |
| `REMOTEOK_TAGS` | RemoteOK 搜索标签，逗号分隔 |
| `WWR_FEEDS` | WeWorkRemotely RSS 地址，逗号分隔 |
| `HOURS_LOOKBACK` | 常规来源回看窗口（Jobicy/HN/WWR，默认24小时） |
| `REMOTEOK_LOOKBACK_HOURS` | RemoteOK 独立回看窗口（默认168=7天）。其列表多为常驻/重发岗、原始发布日期偏旧，24h 窗口会几乎全部误杀；填 0 表示不过滤时间 |
| `REMOTIVE_LOOKBACK_HOURS` | Remotive 独立回看窗口（默认168，同上） |
| `SEARCH_KEYWORDS` | Jobicy/Remotive 的本地关键词预过滤（逗号分隔，命中标题/描述/标签任一即保留）。留空默认按 `REMOTEOK_TAGS`，两者都空则不过滤 |
| `ENABLED_SOURCES` | 启用的数据源：`remoteok,wwr,hn,jobicy,remotive`，可裁剪/排序（如 WWR 被 Cloudflare 拦截时去掉 `wwr`） |
| `TOP_N` | 每天推送数量上限（默认30） |
| `SCORE_THRESHOLD` | 匹配度门槛，低于此分不推（默认60） |
| `SKILL_PROFILE_FILE` | 技能画像文件路径（默认 `skill_profile.txt`，参考 `skill_profile.txt.example` 填写你自己的背景） |
| `TIMEZONE` | 邮件里显示时间的时区（默认 `Asia/Shanghai`） |
| `SENT_HISTORY_FILE` | 已推送历史记录文件 |
| `LOG_DIR` | 运行日志目录（`logs/digest.log`，自动滚动） |
| `SEND_EMPTY_DIGEST` | 今天没有达标岗位时是否仍发一封说明邮件（默认 false） |
| `USE_SYSTEM_PROXY` | 是否使用系统代理（默认 true）。每个请求若走代理失败（如代理软件未开）会自动改直连重试一次 |

### 各邮箱 SMTP 参考

| 邮箱 | SMTP_HOST | 端口 | 密码填什么 |
| --- | --- | --- | --- |
| QQ 邮箱 | `smtp.qq.com` | 465 | 设置→账户→开启SMTP后生成的**授权码** |
| 163 邮箱 | `smtp.163.com` | 465 | 同上，**授权码** |
| Gmail | `smtp.gmail.com` | 465 | Google 账号→安全→**应用专用密码** |

### 不同用户怎么适配（技能画像是核心）

这个项目不绑定任何特定职业背景，评分质量完全取决于你提供的**技能画像**：

1. **复制模板并填写**：`copy skill_profile.txt.example skill_profile.txt`，然后整段替换成你自己的真实背景（工作年限、职业路径、技术栈、核心优势、偏好）。**不要照抄示例**，否则打分会偏离你的实际情况。
2. **同步调整搜索范围**：在 `config.env` 里把 `REMOTEOK_TAGS` 改成与你技术栈相关的标签（RemoteOK 支持的标签如 `python`/`java`/`frontend`/`data`/`devops` 等），标签越多请求越慢，建议 5~10 个。
3. **调整匹配门槛**：想更"挑剔"就调高 `SCORE_THRESHOLD`（如 70~80），想更"海量"就调低（如 50）。
4. **隐私说明**：`config.env` 和 `skill_profile.txt` 已被 `.gitignore` 排除，**不会**被提交到公开仓库，只会上传 `.example` 模板。

## 三、每天 8 点自动推送（Windows 任务计划）

项目自带一键安装脚本 `scripts/install_task.ps1`：

```powershell
# 方式A：当前用户登录后才会运行（普通权限即可）
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1

# 方式B：即使未登录也运行（以管理员身份打开 PowerShell 执行）
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -RunAsSystem
```

其他常用操作：

```powershell
# 改时间（例如早上9点）
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -At "09:00"

# 立即手动触发一次（测试用）
Start-ScheduledTask -TaskName DailyJobDigest

# 查看任务
Get-ScheduledTask -TaskName DailyJobDigest
Get-ScheduledTaskInfo -TaskName DailyJobDigest   # 看上次/下次运行时间

# 卸载
powershell -ExecutionPolicy Bypass -File scripts\uninstall_task.ps1
```

手动运行一次也可以双击 `scripts\run.bat`。

### Linux / macOS 定时推送

```bash
# 每天 08:00 运行（先确认 crontab -e 里 Python 路径）
0 8 * * * cd /path/to/daily-job-digest && /usr/bin/python3 daily_job_digest.py >> logs/cron.log 2>&1
```

macOS 也可用 `launchd`；Linux 桌面可配 systemd timer。核心就是在固定时间执行
`python daily_job_digest.py`（工作目录为项目根目录，保证能读到 `config.env`）。

## 四、项目结构

```
daily-job-digest/
├── daily_job_digest.py        # 主入口（编排整个流程）
├── config.env.example         # 配置模板（复制为 config.env 后填写）
├── config.env                 # 你的真实配置（不入库）
├── skill_profile.txt.example  # 技能画像模板（复制后填写你自己的背景）
├── skill_profile.txt          # 你的真实技能画像（不入库）
├── requirements.txt
├── LICENSE
├── jobdigest/                 # 功能模块
│   ├── config.py              #   配置加载与校验
│   ├── fetchers.py            #   多数据源并行抓取 + 去重（注册表 SOURCE_FUNCS）
│   ├── scorer.py              #   DeepSeek 分批打分（带重试）
│   ├── emailer.py             #   HTML/纯文本邮件构建与发送
│   ├── history.py             #   已推送历史记录（原子写入）
│   └── utils.py               #   日志/HTTP会话/时间/文本工具
├── scripts/
│   ├── setup.py               # 跨平台初始化向导（推荐先跑这个）
│   ├── install_task.ps1       # 一键注册每天8点计划任务(Windows)
│   ├── uninstall_task.ps1
│   └── run.bat                # 手动运行(Windows)
├── .github/workflows/ci.yml   # 提交自动跑测试
├── CONTRIBUTING.md            # 贡献指南
└── logs/                      # 运行日志 + dry-run 预览（不入库）
```

## 五、常见问题

- **提示"缺少必要配置项"**：`config.env` 里 `DEEPSEEK_API_KEY`、`SMTP_USER`、`SMTP_PASS`、`MAIL_TO` 必须填。
- **发送失败 Authentication failed**：`SMTP_PASS` 要填授权码/应用专用密码，不是邮箱登录密码。
- **`[WWR] 首个 feed 失败，判定全站不可达`**：WWR 被 Cloudflare 整体拦截时的正常提示。程序会快速跳过该来源，不影响其他来源抓取。若你的网络长期如此，可在 `ENABLED_SOURCES` 中去掉 `wwr` 避免无效请求。
- **`[RemoteOK] 请求失败`**：多为网络问题或 RemoteOK 限流，程序已自动重试，可查看日志定位。
- **HN 经常 0 条**：HN "Who is Hiring" 是**每月一帖**，只有在每月初那几天才有大量新岗位。非月初运行时，帖子里的新评论多为回复/闲聊，程序会用启发式过滤把这些噪音剔除（避免浪费 DeepSeek 打分 token），因此抓到 0 条是正常现象。如需月初岗位，可临时把 `HOURS_LOOKBACK` 调大（如 720）后手动运行一次。
- **RemoteOK 经常 0 条？**：它返回的大多是"重发/常驻"岗位，原始发布日期很旧，旧逻辑的 24h 窗口会全部误杀。现在改用 `REMOTEOK_LOOKBACK_HOURS`（默认 7 天）抓取，重复岗位由已推送历史去重，不会重复推。
- **今天没有达标的岗位**：可在 `config.env` 调大 `HOURS_LOOKBACK`、放宽 `REMOTEOK_LOOKBACK_HOURS`/`REMOTIVE_LOOKBACK_HOURS`，或调低 `SCORE_THRESHOLD` 后再试。
- **`--dry-run` 不发送邮件**：无论本次有没有达标岗位，都会在 `logs\` 下生成 `preview_*.html` 供你预览邮件效果。
- **一直收不到邮件**：先跑 `python daily_job_digest.py --dry-run` 看打分是否正常、有没有达标岗位；再查 `logs/digest.log`。常见原因：① 当天代理软件没开导致全部来源失败（现在会自动直连重试，通常不再全 0）；② 非月初时 HN 本就没量，而 RemoteOK/Remotive 是常驻岗、靠 7 天窗口兜底；③ `SCORE_THRESHOLD` 太高可调低，或调大 `HOURS_LOOKBACK`/`TOP_N`。
- **中文字符在控制台乱码/报错**：程序已自动将输出切为 UTF-8，正常无需处理。
- **改技能画像 / 适配不同用户**：复制 `skill_profile.txt.example` 为 `skill_profile.txt` 后整段替换成你自己的背景，并在 `config.env` 里同步修改 `REMOTEOK_TAGS`。项目不绑定任何职业背景，打分完全以你的画像为准。
- **避免重复推送**：推送成功的岗位 id 会记入 `sent_job_ids.json`（最多保留5000条），同一天重复运行不会重复推送。

## 六、新增数据源与扩展

内置五类来源，注册表在 `jobdigest/fetchers.py` 的 `SOURCE_FUNCS`：

| 名称 | 类型 | 免费/Key | 特点 |
| --- | --- | --- | --- |
| `remoteok` | JSON API | 无 Key | 标签粒度、量大，但常驻岗多，用 7 天窗口 |
| `wwr` | RSS | 无 Key | 部分网络被 Cloudflare 整体拦截 |
| `hn` | Algolia API | 无 Key | 每月初 Who is Hiring 高峰 |
| `jobicy` | JSON API | 无 Key | 每日更新、新鲜度高，是主要增量来源 |
| `remotive` | JSON API | 无 Key | 常驻列表、更新较慢，作补充 |

想再加来源：在 `fetchers.py` 里写 `def fetch_xxx(cfg) -> list[dict]`（统一字段：`source/id/title/company/tags/description/url/posted_at`），注册进 `SOURCE_FUNCS`/`SOURCE_NAMES`，并在 `ENABLED_SOURCES` 中开启即可，其余流程（去重/打分/推送）无需改动。

## 七、免责说明

自动匹配结果仅供参考。HN "Who is Hiring" 评论区岗位格式不统一，标题可能不完整，请以正文/链接内容为准。
