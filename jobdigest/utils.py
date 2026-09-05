# -*- coding: utf-8 -*-
"""通用工具：日志、HTTP 会话、时间、文本清理。"""
import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout, ProxyError, SSLError
from urllib3.util.retry import Retry
from zoneinfo import ZoneInfo

logger = logging.getLogger("digest.utils")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_dir: str, level: int = logging.INFO) -> None:
    """初始化日志：控制台 + 滚动文件（UTF-8）。"""
    root = logging.getLogger()
    root.setLevel(level)
    if root.handlers:  # 避免重复添加
        return

    fmt = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "digest.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Windows 控制台默认 GBK，强制切到 UTF-8，避免中文打印报错
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_in(tz_name: str) -> datetime:
    """返回指定时区的当前时间；时区无效时回退到 UTC。"""
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return utc_now()


def within_lookback(dt: datetime, hours: int) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (utc_now() - dt) <= timedelta(hours=hours)


def parse_iso_dt(value) -> datetime:
    """解析 ISO 时间串（可带 Z / 时区偏移）；无时区按 UTC。失败返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_session(total: int = 3, backoff: float = 1.0, use_system_proxy: bool = True) -> requests.Session:
    """创建带自动重试（退避）的 HTTP 会话。use_system_proxy=False 时绕过系统代理直连。"""
    session = requests.Session()
    session.trust_env = use_system_proxy
    retry = Retry(
        total=total,
        connect=total,
        read=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def http_get(url: str, *, params=None, headers=None, timeout: int = 20,
             use_system_proxy: bool = True, total: int = 3, backoff: float = 1.0,
             direct_fallback: bool = True) -> requests.Response:
    """带重试的 GET；系统代理开着但连不上（Clash 等未启动导致 ProxyError/
    SSLError/ConnectTimeout）时，自动改为直连再试一次，避免某天代理没开就全军覆没。
    直连也失败时抛最后一个异常。"""
    last_err = None
    for attempt in range(2):
        if attempt == 1 and not (use_system_proxy and direct_fallback):
            break
        use_proxy = use_system_proxy and attempt == 0
        session = new_session(total=total, backoff=backoff, use_system_proxy=use_proxy)
        try:
            return session.get(url, params=params, headers=headers, timeout=timeout)
        except (ProxyError, SSLError, ConnectTimeout) as e:
            last_err = e
            if attempt == 0 and use_system_proxy and direct_fallback:
                logger.warning("经系统代理请求 %s 失败(%s)，改为直连重试一次",
                               url.split("?")[0], e.__class__.__name__)
                continue
            raise
    raise last_err


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str, max_len: int = 0) -> str:
    """去掉 HTML 标签、反转义实体并压缩空白，可选截断。"""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)  # &#x27; -> ' 等
    text = _WS_RE.sub(" ", text).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len] + "…"
    return text


def extract_json_array(text: str):
    """鲁棒解析 LLM 返回的 JSON 数组：剥掉 markdown 围栏、截取第一个 [] 块。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[[\s\S]*\]", t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None
