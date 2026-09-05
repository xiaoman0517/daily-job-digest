# 贡献指南 (Contributing)

欢迎任何形式的贡献：提 Issue、改文档、加新数据源、修 bug。

## 本地开发

```bash
python -m pip install -r requirements.txt
python tests/test_smoke.py        # 冒烟测试（不依赖真实 API Key）
```

## 怎么加一个新的岗位数据源

1. 在 `jobdigest/fetchers.py` 写抓取函数：
   `def fetch_xxx(cfg) -> list[dict]`
   返回字段统一为：
   `source / id / title / company / tags / description / url / posted_at`
   - `description` 请用 `strip_html(..., 1800)` 截断，供 DeepSeek 打分；
   - 尽量用 `utils.http_get`（自带重试与"代理失败→直连"兜底）；
   - 带时间字段的用 `utils.parse_iso_dt` 解析。
2. 注册进 `SOURCE_FUNCS` / `SOURCE_NAMES`（`ENABLED_SOURCES` 里即可开启）。
3. 若涉及新配置项，同步改 `jobdigest/config.py` 的 `DEFAULTS` 与
   `config.env.example`，并在 README「六、新增数据源与扩展」补一行。
4. 补/改 `tests/test_smoke.py` 中对应的纯逻辑测试（不要发真实网络请求）。

## 代码风格与约定

- Python 3.9+，注释与日志用中文（和现有代码一致）；
- 不要在代码、测试、README 中写死任何真实 API Key / 邮箱 / 个人简历；
- 新增测试用例保证在无网络、无 API Key 环境可跑（`tests/test_smoke.py`）。

## 提交前检查清单

- [ ] `python tests/test_smoke.py` 全部通过
- [ ] 未把 `config.env`、`skill_profile.txt`、`logs/`、`sent_job_ids.json` 加进提交
      （可用 `git status` 确认）
- [ ] 若改了抓取逻辑，本地 `python daily_job_digest.py --dry-run` 跑通一次

## 提交 / PR

- 建议按功能拆分提交，提交信息写明改动点；
- PR 说明请描述：改了什么、为什么、怎么验证。
