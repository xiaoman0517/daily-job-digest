#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日远程岗位智能匹配推送
========================================
数据源：RemoteOK(JSON API) + WeWorkRemotely(RSS) + HN "Who is Hiring"(Algolia API)
       + Jobicy / Remotive（无 Key 免费聚合 API），ENABLED_SOURCES 可裁剪
流程：并行抓取新岗位(RemoteOK/Remotive 用独立 7 天窗口) -> 去重 -> DeepSeek打分匹配 -> Top N -> 邮件推送

用法：
    python daily_job_digest.py             # 正常推送（读取 config.env）
    python daily_job_digest.py --dry-run   # 只抓取+打分，生成HTML预览，不发送邮件
    python daily_job_digest.py --config my.env

定时任务（Windows，每天8点自动推送）：
    powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1
    详见 README.md
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobdigest import __version__
from jobdigest.config import Config
from jobdigest.emailer import build_email_html, build_email_plain, send_email
from jobdigest.fetchers import dedupe, fetch_all_jobs
from jobdigest.history import load_sent_ids, save_sent_ids
from jobdigest.scorer import score_jobs
from jobdigest.utils import setup_logging, utc_now

logger = logging.getLogger("digest")


def run(cfg: Config, dry_run: bool = False) -> int:
    logger.info("=== 每日岗位推送启动 v%s ===", __version__)

    # 1) 并行抓取
    all_jobs = fetch_all_jobs(cfg)
    logger.info("各数据源共抓取 %d 条（未去重，详见上方各来源明细）", len(all_jobs))

    # 2) 去重
    all_jobs = dedupe(all_jobs)
    logger.info("跨来源去重后剩余 %d 条", len(all_jobs))

    # 3) 过滤历史已推送
    sent_ids = load_sent_ids(cfg.get("SENT_HISTORY_FILE"))
    new_jobs = [j for j in all_jobs if j["id"] not in sent_ids]
    logger.info("过滤历史已推送，待打分 %d 条", len(new_jobs))

    if not new_jobs:
        logger.info("今天没有新岗位，结束。")
        logger.info("提示：可调大 HOURS_LOOKBACK 扩大抓取范围，例如 48/72 小时。")
        return 0

    # 4) DeepSeek 打分
    scored = score_jobs(new_jobs, cfg)

    # 5) 过滤门槛 + 排序 + 取 Top N
    ranked = []
    for j in new_jobs:
        s = scored.get(j["id"])
        if s and s.get("score", 0) >= cfg.get_int("SCORE_THRESHOLD"):
            ranked.append({**j, **s})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    ranked = ranked[: cfg.get_int("TOP_N")]
    logger.info("匹配度>=%d 的岗位 %d 条，取 Top %d",
                cfg.get_int("SCORE_THRESHOLD"), len(ranked), cfg.get_int("TOP_N"))

    # 6) 构建邮件内容（无论是否达标都先构建，dry-run 时总能输出预览）
    html = build_email_html(ranked, cfg)
    text = build_email_plain(ranked, cfg)

    # 7) dry-run：只保存预览，不发送
    if dry_run:
        log_dir = cfg.get("LOG_DIR") or "logs"
        os.makedirs(log_dir, exist_ok=True)
        out = os.path.join(log_dir, f"preview_{utc_now().strftime('%Y%m%d_%H%M%S')}.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("[dry-run] 未发送邮件，HTML 预览已保存：%s（本次 %d 个达标岗位）", out, len(ranked))
        return 0

    # 8) 发送
    if not ranked:
        logger.info("今天没有达标的岗位。")
        logger.info("提示：可调大 HOURS_LOOKBACK 扩大抓取范围，或调低 SCORE_THRESHOLD 降低门槛。")
        if cfg.get_bool("SEND_EMPTY_DIGEST"):
            logger.info("SEND_EMPTY_DIGEST=true，发送说明邮件。")
            send_email(html, text, cfg)
        return 0

    if send_email(html, text, cfg):
        sent_ids.update(j["id"] for j in ranked)
        save_sent_ids(cfg.get("SENT_HISTORY_FILE"), sent_ids)
        logger.info("已更新历史记录（累计 %d 条）", len(sent_ids))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="每日远程岗位智能匹配推送")
    parser.add_argument("--config", default="config.env", help="配置文件路径（默认 config.env）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只抓取+打分并生成HTML预览，不发送邮件")
    args = parser.parse_args()

    try:
        cfg = Config.load(args.config)
    except SystemExit as e:
        # 配置缺失时也写入日志，便于计划任务排查
        setup_logging("logs")
        logger.error("配置校验失败：%s", str(e).strip())
        raise
    setup_logging(cfg.get("LOG_DIR"))
    try:
        return run(cfg, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.warning("用户中断。")
        return 130
    except Exception:
        logger.exception("主流程异常退出")
        return 1


if __name__ == "__main__":
    sys.exit(main())
