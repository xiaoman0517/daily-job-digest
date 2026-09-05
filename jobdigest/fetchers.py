# -*- coding: utf-8 -*-
"""数据源抓取：RemoteOK / WeWorkRemotely(RSS) / HN Who is Hiring / Jobicy / Remotive。

设计说明
--------
- 所有请求走 utils.http_get：系统代理开着但连不上（如 Clash 未启动）时自动直连重试一次，
  避免某天代理没开就全部来源归零；
- RemoteOK / Remotive 的列表大多是"常驻/重发"岗位，原始发布日期偏旧，
  若沿用 HOURS_LOOKBACK(默认24h) 会把它们几乎全部误杀，因此各自支持独立更长回看窗口
  （REMOTEOK_LOOKBACK_HOURS / REMOTIVE_LOOKBACK_HOURS，默认 7 天），
  重复岗位由 sent_job_ids 历史去重兜底；
- Jobicy / Remotive 用 SEARCH_KEYWORDS 做本地关键词预过滤（命中标题/描述/标签任一即保留），
  避免无关岗位也送去 DeepSeek 打分浪费 token；
- 启用的来源由 ENABLED_SOURCES 控制（如 WWR 被 Cloudflare 拦截时可去掉 wwr）。
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import feedparser

from .utils import http_get, parse_iso_dt, strip_html, utc_now, within_lookback

logger = logging.getLogger("digest.fetchers")

# HN "Who is Hiring" 线程里混有大量对话回复（感谢、询问、自我介绍等），
# 用启发式信号词过滤掉明显的非招聘评论，避免浪费 DeepSeek 打分 token。
_HN_JOB_SIGNALS = (
    "hiring", "remote", "salary", "applicant", "role", "position",
    "senior", "full-stack", "full stack", "backend", "back-end",
    "frontend", "front-end", "engineer", "developer", "full-time",
    "$", "equity", "stack", "team", "resume", "experienced",
)
# 明显的对话/申请类措辞（出现在正文前 240 字符内即判定为非招聘）
_HN_NOISE = (
    "just sent", "sent an email", "filled out", "just applied",
    "talk more", "would love to talk", "thanks for", "thank you",
    "good luck", "congrats", "looking forward", "glad to hear",
    "heard back", "got an offer", "welcome aboard", "nice to meet",
    "appreciate the", "great question",
)

# 归一化：忽略空白 / 连字符 / 下划线差异，使 "machine-learning" 能命中 "machine learning"。
_RE_FLAT = re.compile(r"[\s_\-]+")

# 明显非技术岗的标题特征（仅用于 Jobicy/Remotive 这类大杂烩源的预筛，
# 避免销售/客服/行政岗也送去 DeepSeek 打分浪费 token；
# 注意保留 "sales engineer" 这类技术岗）。
_JUNK_TITLE_RE = re.compile(
    r"account\s+(executive|manager)|customer\s+success|business\s+development|"
    r"recruit(er|ing)|market(ing|er)|copywriter|content\s+writer|"
    r"sales\s+(rep|representative|associate|manager|executive|development|lead|director|specialist|business)|"
    r"virtual\s+assistant|bookkeeper|accountant|talent\s+acquisition|office\s+manager",
    re.IGNORECASE,
)


def _norm_keyword(s: str) -> str:
    return _RE_FLAT.sub("", (s or "").lower())


def _source_keywords(cfg) -> list:
    """返回归一化后的本地预过滤关键词；SEARCH_KEYWORDS 为空时退化为 REMOTEOK_TAGS。"""
    raw = cfg.get_list("SEARCH_KEYWORDS") or cfg.tags
    return [k for k in (_norm_keyword(x) for x in raw) if k]


def _hits(text: str, keywords: list) -> bool:
    """text 命中任一关键词即保留；keywords 为空则不过滤。"""
    if not keywords:
        return True
    t = _RE_FLAT.sub("", (text or "").lower())
    return any(k in t for k in keywords)


def is_probable_job_post(text: str) -> bool:
    """启发式判断一条 HN 评论是否像招聘帖。"""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < 100:  # 真实招聘帖一般较长
        return False
    head = stripped.split("\n")[0].strip().lower()
    if head.startswith(("@", ">", "hey ", "hi ", "thanks ", "thank ")):
        return False
    low = stripped.lower()
    if any(n in low[:240] for n in _HN_NOISE):
        return False
    signals = sum(1 for s in _HN_JOB_SIGNALS if s in low)
    return signals >= 2  # 命中 2 个及以上招聘信号词


def fetch_remoteok(cfg):
    """RemoteOK JSON API：按标签抓取岗位。

    API 的 epoch 是岗位"原始发布日期"，大量每天重发的常驻岗 epoch 很旧，
    用 24h 窗口会全被过滤，因此使用独立的 REMOTEOK_LOOKBACK_HOURS（默认 7 天）。
    """
    hours = cfg.get_int("REMOTEOK_LOOKBACK_HOURS", 168)  # 0 = 不过滤时间
    session_kw = dict(use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"),
                      headers={"User-Agent": cfg.get("USER_AGENT")})
    jobs, seen = [], set()

    for tag in cfg.tags:
        try:
            resp = http_get("https://remoteok.com/api", params={"tag": tag}, timeout=20,
                            total=3, backoff=1.0, **session_kw)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("[RemoteOK] tag=%s 请求失败: %s", tag, e)
            continue

        for item in data:
            # API 返回列表第一条通常是免责声明等 meta 信息，没有 id 字段
            if not isinstance(item, dict) or "id" not in item:
                continue
            jid = f"remoteok_{item['id']}"
            if jid in seen:
                continue
            seen.add(jid)

            epoch = item.get("epoch")
            try:
                posted_dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc) if epoch else None
            except (TypeError, ValueError):
                posted_dt = None
            if posted_dt is None:
                continue
            if hours and not within_lookback(posted_dt, hours):
                continue

            jobs.append({
                "source": "RemoteOK",
                "id": jid,
                "title": (item.get("position") or "").strip(),
                "company": (item.get("company") or "").strip(),
                "tags": [str(t) for t in (item.get("tags") or [])],
                "description": strip_html(item.get("description") or "", 1800),
                "url": item.get("url") or item.get("apply_url") or "",
                "posted_at": posted_dt.isoformat(),
            })
    return jobs


def fetch_wwr(cfg):
    """We Work Remotely RSS 源。

    WWR 在部分网络下会被 Cloudflare 整体拦截（403/超时），因此策略是：
    - 不做请求重试、使用短超时（8s）；
    - 首个 feed 失败即判定全站不可达，跳过其余 feed，避免白白等待。
    （若你长期用不到该源，可在 ENABLED_SOURCES 中去掉 wwr。）
    """
    hours = cfg.get_int("HOURS_LOOKBACK")
    session_kw = dict(use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"),
                      headers={"User-Agent": cfg.get("USER_AGENT")})
    jobs = []

    for idx, feed_url in enumerate(cfg.feeds):
        try:
            resp = http_get(feed_url, timeout=8, total=0, backoff=0.5, **session_kw)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"RSS 解析异常: {parsed.bozo_exception}")
        except Exception as e:
            if idx == 0:
                logger.warning("[WWR] 首个 feed 失败，判定全站不可达/被拦截，跳过其余 feed：%s", e)
                break
            logger.warning("[WWR] %s 请求失败(跳过): %s", feed_url, e)
            continue

        for entry in parsed.entries:
            try:
                posted_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                continue
            if not within_lookback(posted_dt, hours):
                continue

            title = (entry.get("title") or "").strip()
            # WWR 的 RSS 标题格式通常是 "Company: Job Title"
            company = title.split(":", 1)[0].strip() if ":" in title else ""

            jobs.append({
                "source": "WeWorkRemotely",
                "id": f"wwr_{entry.get('id') or entry.get('link')}",
                "title": title,
                "company": company,
                "tags": [t.get("term") for t in (entry.get("tags") or []) if t.get("term")],
                "description": strip_html(entry.get("summary") or "", 1800),
                "url": entry.get("link", ""),
                "posted_at": posted_dt.isoformat(),
            })
    return jobs


def fetch_hn_whoishiring(cfg):
    """Hacker News "Who is Hiring" 评论区岗位（Algolia API）。"""
    hours = cfg.get_int("HOURS_LOOKBACK")
    session_kw = dict(use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"),
                      headers={"User-Agent": cfg.get("USER_AGENT")})
    jobs = []

    try:
        # 找到 whoishiring 账号发布的最新一篇 "Ask HN: Who is hiring"
        resp = http_get("https://hn.algolia.com/api/v1/search_by_date",
                        params={"tags": "story,author_whoishiring", "hitsPerPage": 5},
                        timeout=20, total=3, backoff=1.0, **session_kw)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        story = next((h for h in hits if "who is hiring" in (h.get("title") or "").lower()), None)
        if not story:
            logger.warning("[HN] 没找到最新的 Who is Hiring 帖子")
            return jobs
        story_id = story["objectID"]
        since_ts = int((utc_now() - timedelta(hours=hours)).timestamp())

        resp2 = http_get("https://hn.algolia.com/api/v1/search_by_date",
                         params={
                             "tags": f"comment,story_{story_id}",
                             "numericFilters": f"created_at_i>{since_ts}",
                             "hitsPerPage": 200,
                         },
                         timeout=20, total=3, backoff=1.0, **session_kw)
        resp2.raise_for_status()
        comments = resp2.json().get("hits", [])

        for c in comments:
            text = strip_html(c.get("comment_text") or "")
            if not text:
                continue
            if not is_probable_job_post(text):  # 过滤对话噪音，节省打分 token
                continue
            first_line = text.strip().split("\n")[0][:120]
            jobs.append({
                "source": "HN-WhoIsHiring",
                "id": f"hn_{c['objectID']}",
                "title": first_line,
                "company": "",  # HN 评论没有结构化公司字段，交给 DeepSeek 从正文提取
                "tags": [],
                "description": text[:1500],
                "url": f"https://news.ycombinator.com/item?id={c['objectID']}",
                "posted_at": datetime.fromtimestamp(c["created_at_i"], tz=timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.warning("[HN] 请求失败: %s", e)

    return jobs


def fetch_jobicy(cfg):
    """Jobicy 免费聚合 API（无 Key，每日更新）：
    https://jobicy.com/api/v2/remote-jobs?count=100
    """
    hours = cfg.get_int("HOURS_LOOKBACK")
    keywords = _source_keywords(cfg)
    jobs = []
    try:
        resp = http_get("https://jobicy.com/api/v2/remote-jobs",
                        params={"count": 100}, timeout=20, total=3, backoff=1.0,
                        use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"),
                        headers={"User-Agent": cfg.get("USER_AGENT")})
        resp.raise_for_status()
        items = resp.json().get("jobs", [])
    except Exception as e:
        logger.warning("[Jobicy] 请求失败: %s", e)
        return jobs

    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title = (item.get("jobTitle") or "").strip()
        if not title or _JUNK_TITLE_RE.search(title):
            continue
        posted_dt = parse_iso_dt(item.get("pubDate"))
        if posted_dt is None or not within_lookback(posted_dt, hours):
            continue

        company = (item.get("companyName") or "").strip()
        industry = item.get("jobIndustry")
        tags = industry if isinstance(industry, list) else [str(industry)] if industry else []
        geo = item.get("jobGeo") or ""
        description = strip_html(item.get("jobDescription") or item.get("jobExcerpt") or "", 1800)
        if not description:
            continue

        # 本地关键词预过滤（控制送入打分的量）
        if not _hits(f"{title} {company} {' '.join(map(str, tags))} {geo} {description[:1500]}",
                     keywords):
            continue

        # 地理位置写入正文，便于 DeepSeek 评估时区/远程友好度
        if geo and not description.lstrip().startswith(("📍", "Location")):
            description = f"📍 {geo}\n{description}"

        slug = item.get("jobSlug") or item.get("id")
        jobs.append({
            "source": "Jobicy",
            "id": f"jobicy_{item['id']}",
            "title": title,
            "company": company,
            "tags": tags,
            "description": description,
            "url": item.get("url") or f"https://jobicy.com/jobs/{slug}",
            "posted_at": posted_dt.isoformat(),
        })
    return jobs


def fetch_remotive(cfg):
    """Remotive 免费聚合 API（无 Key，常驻列表，更新节奏较慢）：
    https://remotive.com/api/remote-jobs
    使用 REMOTIVE_LOOKBACK_HOURS（默认 7 天）+ SEARCH_KEYWORDS 本地过滤。
    """
    hours = cfg.get_int("REMOTIVE_LOOKBACK_HOURS", 168)  # 0 = 不过滤时间
    keywords = _source_keywords(cfg)
    jobs = []
    try:
        resp = http_get("https://remotive.com/api/remote-jobs",
                        timeout=20, total=3, backoff=1.0,
                        use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"),
                        headers={"User-Agent": cfg.get("USER_AGENT")})
        resp.raise_for_status()
        items = resp.json().get("jobs", [])
    except Exception as e:
        logger.warning("[Remotive] 请求失败: %s", e)
        return jobs

    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title = (item.get("title") or "").strip()
        if not title or _JUNK_TITLE_RE.search(title):
            continue
        posted_dt = parse_iso_dt(item.get("publication_date"))
        if posted_dt is None:
            continue
        if hours and not within_lookback(posted_dt, hours):
            continue

        company = (item.get("company_name") or "").strip()
        tags = [str(t) for t in (item.get("tags") or []) if t]
        geo = item.get("candidate_required_location") or ""
        if isinstance(geo, (list, tuple)):
            geo = ", ".join(str(x) for x in geo)
        salary = item.get("salary") or ""
        description = strip_html(item.get("description") or "", 1800)
        if not description:
            continue

        if not _hits(f"{title} {company} {' '.join(tags)} {geo} {description[:1500]}", keywords):
            continue

        meta = []
        if geo and not description.lstrip().startswith("📍"):
            meta.append(f"📍 {geo}")
        if salary and str(salary).strip().lower() not in ("", "none"):
            meta.append(f"💰 {salary}")
        if meta:
            description = "\n".join(meta) + "\n" + description

        jobs.append({
            "source": "Remotive",
            "id": f"remotive_{item['id']}",
            "title": title,
            "company": company,
            "tags": tags,
            "description": description,
            "url": item.get("url") or f"https://remotive.com/remote-jobs/{item['id']}",
            "posted_at": posted_dt.isoformat(),
        })
    return jobs


# 来源注册表：ENABLED_SOURCES 里出现的名字 -> 抓取函数 / 日志名
SOURCE_FUNCS = {
    "remoteok": fetch_remoteok,
    "wwr": fetch_wwr,
    "hn": fetch_hn_whoishiring,
    "jobicy": fetch_jobicy,
    "remotive": fetch_remotive,
}
SOURCE_NAMES = {
    "remoteok": "RemoteOK",
    "wwr": "WeWorkRemotely",
    "hn": "HN-WhoIsHiring",
    "jobicy": "Jobicy",
    "remotive": "Remotive",
}


def fetch_all_jobs(cfg):
    """并行抓取 ENABLED_SOURCES 指定的数据源并合并结果。"""
    enabled = cfg.get_list("ENABLED_SOURCES") or list(SOURCE_FUNCS)
    selected = []
    for name in enabled:
        name = name.strip().lower()
        if name in SOURCE_FUNCS:
            selected.append(name)
        else:
            logger.warning("ENABLED_SOURCES 里未知的数据源 %r，已忽略（可选: %s）",
                           name, ", ".join(SOURCE_FUNCS))

    with ThreadPoolExecutor(max_workers=len(selected) or 1) as pool:
        future_to_name = {
            pool.submit(SOURCE_FUNCS[name], cfg): name for name in selected
        }
        jobs = []
        for fut in as_completed(future_to_name):
            name = future_to_name[fut]
            try:
                part = fut.result()
                logger.info("[%s] 抓取到 %d 条", SOURCE_NAMES[name], len(part))
                jobs.extend(part)
            except Exception:
                logger.exception("[%s] 抓取异常", SOURCE_NAMES[name])
    return jobs


def dedupe(jobs):
    """跨来源去重：按「公司 + 标题」归一化。"""
    seen, result = set(), []
    for j in jobs:
        key = re.sub(r"\W+", "", (j.get("company", "") + j.get("title", "")).lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        result.append(j)
    return result
