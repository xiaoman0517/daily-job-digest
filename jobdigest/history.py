# -*- coding: utf-8 -*-
"""已推送岗位的历史记录，避免重复推送同一岗位。"""
import json
import logging
import os

logger = logging.getLogger("digest.history")

MAX_KEEP = 5000  # 只保留最近 N 条，防止文件无限膨胀


def load_sent_ids(path: str) -> set:
    if not path or not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception as e:
        logger.warning("历史文件 %s 读取失败，重新开始记录：%s", path, e)
        return set()


def save_sent_ids(path: str, ids: set) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    trimmed = sorted(ids)[-MAX_KEEP:]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False)
    os.replace(tmp, path)  # 原子替换，避免进程中断写坏文件
