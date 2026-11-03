# -*- coding: utf-8 -*-
"""持久化可公开展示的每日岗位归档。"""
import json
import os
import re

DAILY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
PUBLIC_JOB_FIELDS = (
    "id", "title", "company", "score", "reason", "url",
    "source", "tags", "posted_at", "description",
)


def load_archived_ids(data_dir: str) -> set:
    """读取已归档岗位 ID，避免定时任务重复打分、重复展示。"""
    if not os.path.isdir(data_dir):
        return set()

    ids = set()
    for filename in os.listdir(data_dir):
        if not DAILY_FILE_RE.fullmatch(filename):
            continue
        path = os.path.join(data_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            archive = json.load(f)
        if not isinstance(archive, dict) or not isinstance(archive.get("jobs"), list):
            raise ValueError(f"岗位归档格式无效：{path}")
        ids.update(
            job["id"] for job in archive["jobs"]
            if isinstance(job, dict) and isinstance(job.get("id"), str)
        )
    return ids


def save_daily_archive(data_dir: str, date: str, generated_at: str, jobs: list) -> str:
    """保存当天岗位，合并当天已存在的结果并重建日期索引。"""
    os.makedirs(data_dir, exist_ok=True)
    daily_path = os.path.join(data_dir, f"{date}.json")
    existing_jobs = {}
    if os.path.isfile(daily_path):
        with open(daily_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, dict) or not isinstance(existing.get("jobs"), list):
            raise ValueError(f"岗位归档格式无效：{daily_path}")
        existing_jobs = {
            job["id"]: job for job in existing["jobs"]
            if isinstance(job, dict) and isinstance(job.get("id"), str)
        }

    for job in jobs:
        if not isinstance(job.get("id"), str):
            continue
        existing_jobs[job["id"]] = {
            field: job[field] for field in PUBLIC_JOB_FIELDS if field in job
        }

    payload = {
        "date": date,
        "generated_at": generated_at,
        "count": len(existing_jobs),
        "jobs": sorted(
            existing_jobs.values(),
            key=lambda job: (-int(job.get("score", 0)), job.get("title", "").lower()),
        ),
    }
    _write_json_atomic(daily_path, payload)

    dates = sorted(
        (name[:-5] for name in os.listdir(data_dir) if DAILY_FILE_RE.fullmatch(name)),
        reverse=True,
    )
    _write_json_atomic(os.path.join(data_dir, "index.json"), {"dates": dates})
    return daily_path


def _write_json_atomic(path: str, payload: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
