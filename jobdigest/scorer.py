# -*- coding: utf-8 -*-
"""DeepSeek 打分匹配：分批调用 API，失败自动重试，返回结构鲁棒解析。"""
import json
import logging
import time

from .utils import extract_json_array, new_session

logger = logging.getLogger("digest.scorer")

SYSTEM_PROMPT_TEMPLATE = """你是资深远程岗位筛选助手，帮助一位正在求职的工程师挑选合适的远程岗位。

候选人的技能背景（由候选人本人提供，务必以此为准）：
{profile}

你会收到一个 JSON 数组，每个元素包含 id / title / company / tags / description 字段。
请按数组顺序，逐条评估该岗位与候选人背景的匹配程度，并为每一条都输出评分。

评分维度（满分100）：
1. 技术栈重合度（40%）：岗位技术要求与候选人技能关键词的重合程度；
2. 经验层级匹配（30%）：岗位经验要求与候选人技能画像中的年限/转型阶段是否匹配，避免推荐明显低于或高于其经验的岗位（如纯初级/实习岗、纯管理岗）；
3. 远程友好度（20%）：是否明确远程、对时区的要求是否苛刻；
4. 岗位质量（10%）：薪资是否透明、公司是否靠谱、技术是否前沿。

严格要求：
- 只输出一个合法的 JSON 数组，不要 markdown 代码块标记，不要任何解释性文字；
- 格式：[{{"id": "原始id", "score": 0-100的整数, "reason": "一句话中文说明"}}]；
- 数组中的每条都要打分，不得遗漏，也不得编造列表之外的岗位。"""


def build_system_prompt(profile: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(profile=profile or "(未提供技能背景)")


def _call_api(session, cfg, user_payload: str, system_prompt: str):
    headers = {
        "Authorization": f"Bearer {cfg.get('DEEPSEEK_API_KEY')}",
        "Content-Type": "application/json",
    }
    body = {
        "model": cfg.get("DEEPSEEK_MODEL"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    url = cfg.get("DEEPSEEK_API_URL")
    timeout = cfg.get_int("DEEPSEEK_TIMEOUT", 90)
    max_retries = cfg.get_int("DEEPSEEK_MAX_RETRIES", 2)

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = session.post(url, headers=headers, json=body, timeout=timeout)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not content:
                raise ValueError("返回内容为空")
            return content
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("DeepSeek 调用失败（第%d/%d次）：%s，%ds后重试",
                               attempt + 1, max_retries + 1, e, wait)
                time.sleep(wait)
            else:
                logger.warning("DeepSeek 调用失败（第%d/%d次，放弃）：%s",
                               attempt + 1, max_retries + 1, e)
    logger.error("DeepSeek 调用重试后仍失败：%s", last_err)
    return None


def score_jobs(jobs, cfg):
    """分批调用 DeepSeek 打分，返回 {job_id: {"score": int, "reason": str}}。"""
    if not jobs:
        return {}

    session = new_session(total=cfg.get_int("DEEPSEEK_MAX_RETRIES", 2), backoff=2.0,
                           use_system_proxy=cfg.get_bool("USE_SYSTEM_PROXY"))
    system_prompt = build_system_prompt(cfg.skill_profile)
    scored = {}
    batch_size = max(1, cfg.get_int("DEEPSEEK_BATCH_SIZE", 15))

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        user_payload = json.dumps(
            [
                {
                    "id": j["id"],
                    "title": j["title"],
                    "company": j["company"],
                    "tags": j.get("tags", []),
                    "description": j.get("description", ""),
                }
                for j in batch
            ],
            ensure_ascii=False,
        )

        content = _call_api(session, cfg, user_payload, system_prompt)
        if content is None:
            continue

        results = extract_json_array(content)
        if not isinstance(results, list):
            logger.error("DeepSeek 返回格式无法解析：%s", content[:200])
            continue

        for r in results:
            if not isinstance(r, dict) or "id" not in r:
                continue
            try:
                score = max(0, min(100, int(r.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            scored[r["id"]] = {"score": score, "reason": str(r.get("reason", ""))}
        logger.info("批次 %d-%d 打分完成，累计评分 %d 条", i, i + len(batch), len(scored))
        time.sleep(0.5)  # 简单限速，避免触发 API 频率限制

    return scored
