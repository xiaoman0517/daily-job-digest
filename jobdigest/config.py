# -*- coding: utf-8 -*-
"""配置加载与校验：config.env 文件 + 系统环境变量，含类型解析。"""
import logging
import os

logger = logging.getLogger("digest.config")

# 内置默认值（可被 config.env / 系统环境变量覆盖）
DEFAULTS = {
    # ---- DeepSeek ----
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_API_URL": "https://api.deepseek.com/v1/chat/completions",
    "DEEPSEEK_MODEL": "deepseek-chat",
    "DEEPSEEK_BATCH_SIZE": "15",
    "DEEPSEEK_TIMEOUT": "90",
    "DEEPSEEK_MAX_RETRIES": "2",
    # ---- 邮件 ----
    "SMTP_HOST": "smtp.qq.com",
    "SMTP_PORT": "465",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "MAIL_TO": "",
    "MAIL_SENDER_NAME": "每日远程岗位推荐",
    # ---- 抓取 ----
    # 默认标签为通用技术栈集合；不同用户请按自己的技术栈修改（见 config.env.example）
    "REMOTEOK_TAGS": (
        "python,javascript,typescript,backend,frontend,fullstack,"
        "machine-learning,data,devops"
    ),
    "WWR_FEEDS": (
        "https://weworkremotely.com/categories/remote-programming-jobs.rss,"
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss,"
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss,"
        "https://weworkremotely.com/categories/remote-data-jobs.rss"
    ),
    "HOURS_LOOKBACK": "24",
    # RemoteOK/Remotive 的列表多为"常驻/重发"岗，原始发布日期偏旧；
    # 24h 窗口会把它们几乎全部误杀，故单独用更长回看窗口（填 0 = 不过滤时间，靠历史去重）。
    "REMOTEOK_LOOKBACK_HOURS": "168",
    "REMOTIVE_LOOKBACK_HOURS": "168",
    # Jobicy/Remotive 等新聚合源的本地关键词预过滤（命中标题/描述/标签任一即保留）。
    # 留空则退化为用 REMOTEOK_TAGS 过滤；两者都为空则不过滤（会多花打分 token）。
    "SEARCH_KEYWORDS": (
        "ai,llm,agent,rag,python,machine-learning,deep-learning,computer-vision,"
        "pytorch,data,backend,frontend,fullstack,cloud,aws,devops,software"
    ),
    # 启用的数据源（可裁剪/调整顺序）：remoteok / wwr / hn / jobicy / remotive。
    # 例：WWR 常被 Cloudflare 拦截时可去掉 wwr。
    "ENABLED_SOURCES": "remoteok,wwr,hn,jobicy,remotive",
    "TOP_N": "30",
    "SCORE_THRESHOLD": "60",
    # ---- 技能画像 ----
    "SKILL_PROFILE_FILE": "skill_profile.txt",
    # ---- 其他 ----
    "TIMEZONE": "Asia/Shanghai",
    "SENT_HISTORY_FILE": "sent_job_ids.json",
    "LOG_DIR": "logs",
    "SEND_EMPTY_DIGEST": "false",
    # 是否使用系统代理（Windows 系统设置里的代理会被 requests 自动读取）。
    # 若你的代理（Clash/V2Ray 等）未开启或连接失败，可设为 false 直连。
    "USE_SYSTEM_PROXY": "true",
    "USER_AGENT": "Mozilla/5.0 (personal job digest script)",
}

# 必须由用户填写（配置文件中留空会导致启动失败并给出提示）
REQUIRED = ("DEEPSEEK_API_KEY", "SMTP_USER", "SMTP_PASS", "MAIL_TO")

INT_KEYS = {
    "SMTP_PORT", "DEEPSEEK_BATCH_SIZE", "DEEPSEEK_TIMEOUT",
    "DEEPSEEK_MAX_RETRIES", "HOURS_LOOKBACK", "TOP_N", "SCORE_THRESHOLD",
    "REMOTEOK_LOOKBACK_HOURS", "REMOTIVE_LOOKBACK_HOURS",
}
BOOL_KEYS = {"SEND_EMPTY_DIGEST"}
LIST_KEYS = {"REMOTEOK_TAGS", "WWR_FEEDS", "MAIL_TO",
             "SEARCH_KEYWORDS", "ENABLED_SOURCES"}

# 内置技能画像（兜底模板）。
# 开源后不再内置任何个人背景，仅当用户未配置 SKILL_PROFILE_FILE 时给出引导。
# 强烈建议每个用户通过 skill_profile.txt 提供自己的真实背景（参考 skill_profile.txt.example）。
BUILTIN_SKILL_PROFILE = """【提示】你还没有配置技能画像！
请在 config.env 中设置 SKILL_PROFILE_FILE 指向你自己的画像文件（参考仓库里的 skill_profile.txt.example），
并填写真实背景，例如：
- 工作年限与职业路径；
- 主要技术栈（编程语言 / 框架 / 云平台 / 工具）；
- 核心优势与代表性项目；
- 目标岗位类型与偏好（远程 / 时区 / 行业 / 薪资）。
配置之前，下面的打分将基于这段通用提示，匹配效果可能不理想。"""

# skill_profile 模板占位标记：.example / setup.py 生成的引导模板都含此句。
# 加载画像时若仍含该标记，说明用户还没替换成真实背景，给出提醒避免"照抄示例打分"。
PROFILE_PLACEHOLDER_MARK = "请整段替换成你自己的真实背景"

# setup.py 首次运行写入的空白引导模板（不含虚构简历内容）
GUIDED_PROFILE_TEMPLATE = """# ============================================================
# 技能画像 —— DeepSeek 打分依据，请填写你自己的【真实】背景。
# 写得越具体越准。删除示例标记行后逐项填写即可。
# ============================================================
【示例，请整段替换成你自己的真实背景】
工作年限与职业路径（例：5年经验，后端开发 → AI 应用开发）：
（请填写）

主要技术栈：编程语言 / 框架 / 云平台 / 工具：
（请填写）

核心优势与代表性项目：
（请填写）

目标岗位类型与偏好（远程 / 时区 / 行业 / 薪资）：
（请填写）
"""


def parse_env_file(path: str) -> dict:
    """解析 .env 格式文件：# 注释、KEY=VALUE、支持单双引号包裹的值。"""
    values = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if not key:
                continue
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            values[key] = val
    return values


class Config:
    def __init__(self, data: dict, path: str = ""):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, env_file: str = "config.env"):
        """加载配置。优先级：系统环境变量 > config.env 文件 > 内置默认值。"""
        env_file = os.path.abspath(env_file)
        data = dict(DEFAULTS)
        if os.path.exists(env_file):
            data.update(parse_env_file(env_file))
        else:
            print(f"[配置] 未找到配置文件 {env_file}，将仅使用系统环境变量/内置默认值")
        for key in list(data):  # 系统环境变量非空则覆盖
            val = os.environ.get(key)
            if val:
                data[key] = val
        cfg = cls(data, env_file)
        cfg._validate()
        return cfg

    def _validate(self) -> None:
        missing = [k for k in REQUIRED if not self.get(k)]
        if missing:
            raise SystemExit(
                "\n[配置错误] 缺少必要配置项: " + ", ".join(missing)
                + "\n  请在 " + self.path + " 中填写（参考 config.env.example），"
                + "或设置同名系统环境变量。\n"
            )

    # ---------- 基础访问 ----------
    def get(self, key: str, default: str = "") -> str:
        val = self._data.get(key, "")
        return val if val else default

    def get_int(self, key: str, default: int = 0) -> int:
        val = self._data.get(key, "")
        if val == "":
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str) -> bool:
        return str(self._data.get(key, "false")).strip().lower() in ("1", "true", "yes", "on")

    def get_list(self, key: str) -> list:
        raw = self._data.get(key, "")
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    # ---------- 派生属性 ----------
    @property
    def tags(self) -> list:
        return self.get_list("REMOTEOK_TAGS")

    @property
    def feeds(self) -> list:
        return self.get_list("WWR_FEEDS")

    @property
    def mail_to(self) -> list:
        return self.get_list("MAIL_TO")

    @property
    def tz_name(self) -> str:
        return self.get("TIMEZONE", "UTC")

    @property
    def skill_profile(self) -> str:
        """返回技能画像文本；未配置/文件缺失/为空时回退内置模板并给出提示。"""
        f = self.get("SKILL_PROFILE_FILE")
        if f and os.path.exists(f):
            with open(f, "r", encoding="utf-8") as fp:
                content = fp.read().strip()
            if content:
                if PROFILE_PLACEHOLDER_MARK in content:
                    logger.warning(
                        "技能画像文件 %s 仍是模板占位内容（未删除「%s」），"
                        "请替换成你自己的真实背景，否则打分没有意义。",
                        f, PROFILE_PLACEHOLDER_MARK)
                return content
            logger.warning("技能画像文件 %s 为空，将使用内置模板（请填写你的真实背景）", f)
        elif f:
            logger.warning("技能画像文件 %s 不存在，将使用内置模板（请创建该文件，参考 skill_profile.txt.example）", f)
        else:
            logger.warning("未配置 SKILL_PROFILE_FILE，将使用内置模板（强烈建议配置你自己的技能画像）")
        return BUILTIN_SKILL_PROFILE

    def __repr__(self):  # 方便调试，隐藏敏感字段
        masked = {k: ("****" if k in REQUIRED else v) for k, v in self._data.items()}
        return f"Config({masked})"
