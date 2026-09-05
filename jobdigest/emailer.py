# -*- coding: utf-8 -*-
"""邮件构建与发送：HTML 美化 + 纯文本兜底 + SSL/STARTTLS 自适应。"""
import html
import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .utils import now_in

logger = logging.getLogger("digest.emailer")

SOURCE_BADGE = {
    "RemoteOK": ("#16a34a", "RemoteOK"),
    "WeWorkRemotely": ("#2563eb", "WWR"),
    "HN-WhoIsHiring": ("#ea580c", "HN"),
    "Jobicy": ("#7c3aed", "Jobicy"),
    "Remotive": ("#0d9488", "Remotive"),
}


def _score_color(score: int) -> str:
    if score >= 85:
        return "#16a34a"
    if score >= 70:
        return "#2563eb"
    return "#d97706"


def _job_row(j):
    color = _score_color(j["score"])
    title = html.escape(j["title"])
    company = html.escape(j.get("company") or "未知公司")
    reason = html.escape(j.get("reason", ""))
    url = html.escape(j.get("url", ""), quote=True)
    source = j.get("source", "")
    badge_color, badge_text = SOURCE_BADGE.get(source, ("#6b7280", source))
    tags = "".join(
        f'<span style="display:inline-block;background:#f1f5f9;border-radius:4px;'
        f'padding:2px 6px;margin:2px;font-size:11px;color:#475569;">{html.escape(t)}</span>'
        for t in (j.get("tags") or [])[:5]
    )
    posted = html.escape((j.get("posted_at") or "")[:10])
    return f"""
        <tr style="border-bottom:1px solid #eef2f6;">
          <td style="padding:14px 10px;white-space:nowrap;">
            <span style="display:inline-block;min-width:38px;text-align:center;padding:4px 8px;border-radius:6px;font-weight:bold;font-size:14px;color:#fff;background:{color};">{j['score']}</span>
          </td>
          <td style="padding:14px 10px;">
            <a href="{url}" target="_blank" style="font-size:15px;color:#111827;text-decoration:none;font-weight:600;">{title}</a>
            <div style="margin-top:4px;color:#6b7280;font-size:12px;">
              {company}
              <span style="display:inline-block;background:{badge_color};color:#fff;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:6px;">{badge_text}</span>
              {f'<span style="margin-left:6px;">发布于 {posted}</span>' if posted else ''}
            </div>
            {f'<div style="margin-top:4px;">{tags}</div>' if tags else ''}
          </td>
          <td style="padding:14px 10px;font-size:13px;color:#4b5563;line-height:1.5;">{reason}</td>
        </tr>"""


def build_email_html(ranked, cfg):
    """构建邮件 HTML 正文。ranked 为空时输出"今日无匹配岗位"说明。"""
    date_str = now_in(cfg.tz_name).strftime("%Y-%m-%d")

    if ranked:
        rows = "".join(_job_row(j) for j in ranked)
        table = f"""
      <table style="border-collapse:collapse;width:100%;">
        <tr style="background:#f9fafb;text-align:left;">
          <th style="padding:10px;font-size:12px;color:#6b7280;">分数</th>
          <th style="padding:10px;font-size:12px;color:#6b7280;">职位</th>
          <th style="padding:10px;font-size:12px;color:#6b7280;">匹配理由</th>
        </tr>
        {rows}
      </table>"""
        summary = f"共筛选出 {len(ranked)} 个高匹配岗位，按匹配度排序"
    else:
        table = '<p style="color:#6b7280;font-size:14px;">今天没有达到筛选门槛的新岗位，明天继续~</p>'
        summary = "今日暂无高匹配岗位"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI','Microsoft YaHei',Arial,sans-serif;">
  <div style="max-width:820px;margin:0 auto;padding:24px 16px;">
    <div style="background:#ffffff;border-radius:12px;padding:28px 26px;box-shadow:0 1px 4px rgba(0,0,0,.08);">
      <h1 style="margin:0 0 6px;font-size:22px;color:#111827;">每日远程岗位推荐 <span style="color:#6b7280;font-weight:normal;font-size:16px;">{date_str}</span></h1>
      <p style="margin:0 0 20px;color:#6b7280;font-size:13px;">{summary}</p>
      {table}
      <p style="margin:24px 0 0;color:#9ca3af;font-size:11px;">本邮件由 daily-job-digest 自动生成 · 匹配结果仅供参考</p>
    </div>
  </div>
</body>
</html>"""


def build_email_plain(ranked, cfg):
    """构建纯文本兜底正文。"""
    date_str = now_in(cfg.tz_name).strftime("%Y-%m-%d")
    lines = [f"每日远程岗位推荐 {date_str}", f"共 {len(ranked)} 个岗位，按匹配度排序：", ""]
    for i, j in enumerate(ranked, 1):
        lines.append(f"{i}. [{j['score']}] {j['title']} - {j.get('company') or '未知'} ({j.get('source')})")
        lines.append(f"   {j.get('url')}")
        if j.get("reason"):
            lines.append(f"   {j['reason']}")
        lines.append("")
    return "\n".join(lines)


def send_email(html_body: str, text_body: str, cfg) -> bool:
    """发送邮件。返回是否成功。465 端口用 SSL，其余用 STARTTLS。"""
    if not (cfg.get("SMTP_USER") and cfg.get("SMTP_PASS") and cfg.mail_to):
        logger.warning("SMTP 配置不完整，无法发送邮件（已跳过）。")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(f"每日远程岗位推荐 {now_in(cfg.tz_name).strftime('%Y-%m-%d')}", "utf-8")
    msg["From"] = formataddr((str(Header(cfg.get("MAIL_SENDER_NAME", "每日远程岗位推荐"), "utf-8")),
                              cfg.get("SMTP_USER")))
    msg["To"] = ", ".join(cfg.mail_to)
    msg.attach(MIMEText(text_body or "请查看邮件", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    host = cfg.get("SMTP_HOST")
    port = cfg.get_int("SMTP_PORT") or 465
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        with server:
            server.login(cfg.get("SMTP_USER"), cfg.get("SMTP_PASS"))
            server.sendmail(cfg.get("SMTP_USER"), cfg.mail_to, msg.as_string())
        logger.info("邮件已发送至 %s", ", ".join(cfg.mail_to))
        return True
    except Exception as e:
        logger.exception("邮件发送失败：%s", e)
        return False
