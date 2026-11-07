# -*- coding: utf-8 -*-
"""冒烟测试：不依赖真实 API Key，验证核心模块逻辑。
运行：python -m pytest tests -q  或  python tests/test_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from jobdigest.config import Config
from jobdigest.emailer import build_email_html, build_email_plain
from jobdigest.history import load_sent_ids, save_sent_ids
from jobdigest.utils import extract_json_array, strip_html, within_lookback


def make_cfg(**overrides):
    data = {
        "SMTP_USER": "sender@example.com", "SMTP_PASS": "app-password",
        "MAIL_TO": "me@example.com", "SMTP_PORT": "465", "SMTP_HOST": "smtp.qq.com",
        "TIMEZONE": "Asia/Shanghai", "SENT_HISTORY_FILE": "",
        "LOG_DIR": "", "SKILL_PROFILE_FILE": "", "DEEPSEEK_API_KEY": "sk-test",
        "DEEPSEEK_API_URL": "", "DEEPSEEK_MODEL": "deepseek-chat",
        "DEEPSEEK_BATCH_SIZE": "15", "DEEPSEEK_TIMEOUT": "90", "DEEPSEEK_MAX_RETRIES": "2",
        "REMOTEOK_TAGS": "python", "WWR_FEEDS": "", "HOURS_LOOKBACK": "24",
        "TOP_N": "30", "SCORE_THRESHOLD": "60", "SEND_EMPTY_DIGEST": "false",
        "MAIL_SENDER_NAME": "测试", "USER_AGENT": "test-agent", "USE_SYSTEM_PROXY": "false",
    }
    data.update(overrides)
    return Config(data)


def test_strip_html():
    assert strip_html("<b>Hello</b> &amp;  <i>world</i>") == "Hello & world"
    assert strip_html("<p>long</p>", max_len=3) == "lon…"
    assert strip_html("it&#x27;s cool") == "it's cool"  # HTML 实体反转义


def test_extract_json_array():
    r1 = extract_json_array('```json\n[{"id":"a","score":80}]\n```')
    assert r1 == [{"id": "a", "score": 80}]
    r2 = extract_json_array('好的，结果如下：[{"id":"b","score":70,"reason":"匹配"}] 完毕')
    assert r2 == [{"id": "b", "score": 70, "reason": "匹配"}]
    assert extract_json_array("无法解析的内容") is None


def test_within_lookback():
    assert within_lookback(datetime.now(timezone.utc) - timedelta(hours=1), 24)
    assert not within_lookback(datetime.now(timezone.utc) - timedelta(hours=48), 24)


def test_history_roundtrip(tmp_path):
    path = os.path.join(str(tmp_path), "hist_sent.json")
    save_sent_ids(path, {"x", "y"})
    assert load_sent_ids(path) == {"x", "y"}
    assert load_sent_ids(os.path.join(str(tmp_path), "missing.json")) == set()


def test_email_html_escapes():
    cfg = make_cfg()
    sample = [{
        "id": "1", "title": "<script>alert(1)</script> Python Dev",
        "company": "ACME & Co", "score": 88, "reason": "技术栈高度匹配",
        "url": "https://x.com/j?q=1&r=2", "source": "RemoteOK",
        "tags": ["python", "aws"], "posted_at": "2026-08-25T10:00:00+00:00",
    }]
    h = build_email_html(sample, cfg)
    assert "<script>" not in h and "<script" not in h.replace("&lt;script", "")  # XSS 标签已转义
    assert "&lt;script&gt;" in h  # 原始标签被转义为纯文本
    assert "ACME &amp; Co" in h
    assert "88" in h
    p = build_email_plain(sample, cfg)
    assert "Python Dev" in p


def test_email_html_empty():
    h = build_email_html([], make_cfg())
    assert "没有达到" in h


def test_dedupe():
    from jobdigest.fetchers import dedupe
    jobs = [
        {"id": "a", "company": "ACME", "title": "Python Dev"},
        {"id": "b", "company": "ACME", "title": "Python Dev"},   # 重复
        {"id": "c", "company": "", "title": "Other Job"},
    ]
    out = dedupe(jobs)
    assert len(out) == 2 and out[0]["id"] == "a"


def test_is_probable_job_post():
    from jobdigest.fetchers import is_probable_job_post

    job_post = (
        "Acme Inc is hiring a Senior Remote Backend Engineer. "
        "Stack: Python, FastAPI, AWS. Salary $150k-180k, full-time, remote friendly. Apply via email."
    )
    assert is_probable_job_post(job_post) is True

    noise = "I just filled out the form. Looking forward to having a conversation!"
    assert is_probable_job_post(noise) is False

    reply = "@user123 thanks for the info, good luck with your search!"
    assert is_probable_job_post(reply) is False

    short = "We are hiring!"
    assert is_probable_job_post(short) is False

    conversation = (
        "Hey Ernel, I just sent an email - if you&#x27;re still hiring it would be cool to talk more. "
        "I have 5 years of experience with Python and would love to work remote."
    )
    assert is_probable_job_post(conversation) is False


def test_config_list_parsing():
    cfg = make_cfg(MAIL_TO="a@x.com, b@x.com ,c@x.com")
    assert cfg.mail_to == ["a@x.com", "b@x.com", "c@x.com"]


def test_web_export_does_not_require_mail():
    cfg = Config({"DEEPSEEK_API_KEY": "sk-test"})
    cfg._validate(require_mail=False)
    try:
        cfg._validate()
    except SystemExit:
        pass
    else:
        raise AssertionError("normal email mode must still require SMTP settings")


def test_skill_profile_adaptation(tmp_path):
    """技能画像适配：未配置时用内置模板；配置后读取文件内容；文件缺失时回退。"""
    from jobdigest.config import BUILTIN_SKILL_PROFILE

    # 1) 未配置 -> 内置模板（含引导提示）
    cfg = make_cfg(SKILL_PROFILE_FILE="")
    assert cfg.skill_profile == BUILTIN_SKILL_PROFILE
    assert "还没有配置技能画像" in cfg.skill_profile

    # 2) 配置了文件 -> 读文件内容
    my_profile = os.path.join(str(tmp_path), "my_profile.txt")
    with open(my_profile, "w", encoding="utf-8") as f:
        f.write("5年后端经验，Python/Go，擅长RAG应用。")
    cfg2 = make_cfg(SKILL_PROFILE_FILE=my_profile)
    assert cfg2.skill_profile == "5年后端经验，Python/Go，擅长RAG应用。"

    # 3) 文件缺失 -> 回退内置模板
    cfg3 = make_cfg(SKILL_PROFILE_FILE=os.path.join(str(tmp_path), "not_exist.txt"))
    assert cfg3.skill_profile == BUILTIN_SKILL_PROFILE

    # GitHub Actions can provide the profile from an Actions secret.
    cfg4 = make_cfg(SKILL_PROFILE_TEXT="数据分析师，熟悉 SQL 和 Python。")
    assert cfg4.skill_profile == "数据分析师，熟悉 SQL 和 Python。"


def test_web_archive_roundtrip(tmp_path):
    import json

    from jobdigest.web import load_archived_ids, save_daily_archive

    data_dir = os.path.join(str(tmp_path), "archive-data")
    first = {"id": "job-1", "title": "Engineer", "score": 88, "url": "https://example.com"}
    save_daily_archive(data_dir, "2026-11-03", "2026-11-03T00:00:00+00:00", [first])
    save_daily_archive(data_dir, "2026-11-03", "2026-11-03T01:00:00+00:00", [
        {"id": "job-2", "title": "Analyst", "score": 76},
    ])

    with open(os.path.join(data_dir, "2026-11-03.json"), encoding="utf-8") as f:
        archive = json.load(f)
    with open(os.path.join(data_dir, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    assert archive["count"] == 2
    assert index["dates"] == ["2026-11-03"]
    assert load_archived_ids(data_dir) == {"job-1", "job-2"}


def test_run_web_export_archives_once(tmp_path):
    from unittest.mock import patch

    import daily_job_digest
    from jobdigest.web import load_archived_ids

    data_dir = os.path.join(str(tmp_path), "run-data")
    cfg = make_cfg(
        WEB_DATA_DIR=data_dir,
        SENT_HISTORY_FILE=os.path.join(str(tmp_path), "run_sent.json"),
    )
    fake_jobs = [{
        "id": "web-job", "source": "RemoteOK", "title": "Senior Analyst",
        "company": "ACME", "tags": ["python"], "description": "Analytics",
        "url": "https://example.com/job", "posted_at": "2026-11-03T08:00:00+00:00",
    }]
    with patch.object(daily_job_digest, "fetch_all_jobs", return_value=fake_jobs), \
         patch.object(daily_job_digest, "score_jobs", return_value={
             "web-job": {"score": 91, "reason": "经验匹配"},
         }) as score:
        assert daily_job_digest.run(cfg, web_export=True) == 0
        assert daily_job_digest.run(cfg, web_export=True) == 0
    assert score.call_count == 1
    assert load_archived_ids(data_dir) == {"web-job"}
    assert not os.path.exists(cfg.get("SENT_HISTORY_FILE"))


def test_score_jobs_mocked():
    """用 mock 的 API 响应验证打分管道。"""
    import jobdigest.scorer as scorer
    from unittest.mock import patch

    cfg = make_cfg(DEEPSEEK_BATCH_SIZE="2")
    fake_jobs = [
        {"id": "j1", "title": "AI Engineer", "company": "X", "tags": ["python"], "description": "..."},
        {"id": "j2", "title": "Junior", "company": "Y", "tags": [], "description": "..."},
    ]
    fake_response = '[{"id":"j1","score":88,"reason":"高度匹配"},{"id":"j2","score":30,"reason":"初级岗"}]'
    with patch.object(scorer, "_call_api", return_value=fake_response):
        scored = scorer.score_jobs(fake_jobs, cfg)
    assert scored["j1"] == {"score": 88, "reason": "高度匹配"}
    assert scored["j2"]["score"] == 30


def test_score_jobs_retry_and_parse():
    """验证：首次返回带 markdown 围栏也能解析；全部失败不崩溃。"""
    import jobdigest.scorer as scorer
    from unittest.mock import patch

    cfg = make_cfg(DEEPSEEK_MAX_RETRIES="1")
    fake_jobs = [{"id": "a", "title": "t", "company": "c", "tags": [], "description": "d"}]
    with patch.object(scorer, "_call_api", return_value="```json\n[{\"id\":\"a\",\"score\":75,\"reason\":\"ok\"}]\n```"):
        scored = scorer.score_jobs(fake_jobs, cfg)
    assert scored["a"]["score"] == 75

    with patch.object(scorer, "_call_api", return_value=None):  # 调用全部失败
        assert scorer.score_jobs(fake_jobs, cfg) == {}


def test_run_dry_run(tmp_path):
    """端到端编排测试：mock 抓取与打分，验证 dry-run 生成预览且不写历史。"""
    from unittest.mock import patch

    import daily_job_digest

    cfg = make_cfg(LOG_DIR=str(tmp_path), SENT_HISTORY_FILE=os.path.join(str(tmp_path), "run_sent.json"))
    fake_jobs = [
        {"id": "r1", "source": "RemoteOK", "title": "Senior ML Engineer", "company": "ACME",
         "tags": ["python"], "description": "PyTorch + AWS", "url": "https://x.com/1",
         "posted_at": "2026-08-25T10:00:00+00:00"},
        {"id": "r2", "source": "RemoteOK", "title": "Intern", "company": "ACME",
         "tags": [], "description": "intern", "url": "https://x.com/2",
         "posted_at": "2026-08-25T10:00:00+00:00"},
    ]
    fake_scored = {"r1": {"score": 92, "reason": "技术栈完全匹配"}}
    with patch.object(daily_job_digest, "fetch_all_jobs", return_value=fake_jobs), \
         patch.object(daily_job_digest, "score_jobs", return_value=fake_scored):
        code = daily_job_digest.run(cfg, dry_run=True)
    assert code == 0
    # dry-run 不应记录历史
    assert not os.path.exists(cfg.get("SENT_HISTORY_FILE"))
    # 预览 HTML 已生成
    previews = [f for f in os.listdir(str(tmp_path)) if f.startswith("preview_")]
    assert len(previews) == 1
    with open(os.path.join(str(tmp_path), previews[0]), encoding="utf-8") as f:
        assert "Senior ML Engineer" in f.read()


def test_run_dry_run_empty(tmp_path):
    """0 个达标岗位时，dry-run 也应生成预览（空态页面）。"""
    from unittest.mock import patch

    import daily_job_digest

    cfg = make_cfg(LOG_DIR=str(tmp_path), SENT_HISTORY_FILE=os.path.join(str(tmp_path), "empty_sent.json"))
    fake_jobs = [{
        "id": "r1", "source": "HN-WhoIsHiring", "title": "Some job", "company": "",
        "tags": [], "description": "d", "url": "https://x.com/1", "posted_at": "2026-08-25T10:00:00+00:00",
    }]
    with patch.object(daily_job_digest, "fetch_all_jobs", return_value=fake_jobs), \
         patch.object(daily_job_digest, "score_jobs", return_value={}):  # 全部低于门槛
        code = daily_job_digest.run(cfg, dry_run=True)
    assert code == 0
    previews = [f for f in os.listdir(str(tmp_path)) if f.startswith("preview_")]
    assert len(previews) == 1
    with open(os.path.join(str(tmp_path), previews[0]), encoding="utf-8") as f:
        assert "没有达到" in f.read()


def test_run_publish_archives_and_sends(tmp_path):
    """--publish：同一次运行归档 + 发信（网页与邮件同源）。"""
    import json
    from unittest.mock import patch

    import daily_job_digest

    data_dir = os.path.join(str(tmp_path), "publish-data")
    cfg = make_cfg(
        LOG_DIR=str(tmp_path),
        SENT_HISTORY_FILE=os.path.join(str(tmp_path), "publish_sent.json"),
        WEB_DATA_DIR=data_dir,
    )
    fake_jobs = [{
        "id": "p1", "source": "Jobicy", "title": "ML Engineer", "company": "ACME",
        "tags": ["ai"], "description": "LLM + PyTorch", "url": "https://example.com/p1",
        "posted_at": "2026-11-03T08:00:00+00:00",
    }]
    with patch.object(daily_job_digest, "fetch_all_jobs", return_value=fake_jobs), \
         patch.object(daily_job_digest, "score_jobs", return_value={
             "p1": {"score": 82, "reason": "匹配"},
         }), \
         patch.object(daily_job_digest, "send_email", return_value=True) as mocked_send:
        assert daily_job_digest.run(cfg, web_export=True, send_mail=True) == 0
    assert mocked_send.call_count == 1

    with open(os.path.join(data_dir, "index.json"), encoding="utf-8") as f:
        assert json.load(f)["dates"]
    daily = [f for f in os.listdir(data_dir) if f.endswith(".json") and f != "index.json"][0]
    with open(os.path.join(data_dir, daily), encoding="utf-8") as f:
        archive = json.load(f)
    assert archive["count"] == 1
    assert archive["jobs"][0]["id"] == "p1"


def test_run_publish_skips_archive_when_email_fails(tmp_path):
    """发信失败时不写归档，避免岗位被永久跳过。"""
    from unittest.mock import patch

    import daily_job_digest

    data_dir = os.path.join(str(tmp_path), "publish-fail-data")
    cfg = make_cfg(
        LOG_DIR=str(tmp_path),
        SENT_HISTORY_FILE=os.path.join(str(tmp_path), "publish_fail_sent.json"),
        WEB_DATA_DIR=data_dir,
    )
    fake_jobs = [{
        "id": "p2", "source": "Jobicy", "title": "AI Engineer", "company": "ACME",
        "tags": ["ai"], "description": "LLM", "url": "https://example.com/p2",
        "posted_at": "2026-11-03T08:00:00+00:00",
    }]
    with patch.object(daily_job_digest, "fetch_all_jobs", return_value=fake_jobs), \
         patch.object(daily_job_digest, "score_jobs", return_value={
             "p2": {"score": 88, "reason": "匹配"},
         }), \
         patch.object(daily_job_digest, "send_email", return_value=False):
        assert daily_job_digest.run(cfg, web_export=True, send_mail=True) == 0

    archived = [f for f in os.listdir(data_dir) if f.endswith(".json")] if os.path.isdir(data_dir) else []
    assert not archived


if __name__ == "__main__":
    import tempfile
    import traceback

    tmp = tempfile.mkdtemp()
    passed = failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                try:
                    fn(tmp)
                except TypeError:
                    fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
