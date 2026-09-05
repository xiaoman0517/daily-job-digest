#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台一键初始化向导（Windows / Linux / macOS 通用）。

做什么：
  1. 若缺少 config.env —— 从 config.env.example 复制；
  2. 若缺少 skill_profile.txt —— 生成"空白引导模板"（不含虚构简历，避免照抄示例）；
  3. 交互式引导填写：DeepSeek API Key、发件邮箱(SMTP)、收件人、搜索标签；
  4. 校验必填项是否齐全，可选的直接跑一次 --dry-run 预览。

安全性：只修改当前目录的 config.env / skill_profile.txt（两者均已被 .gitignore 排除），
不会上传任何信息到网络（除运行时你主动调用的 DeepSeek/SMTP/数据源接口外）。

用法：
    python scripts/setup.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # 便于 import jobdigest.config 复用模板常量
os.chdir(ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from jobdigest.config import GUIDED_PROFILE_TEMPLATE, PROFILE_PLACEHOLDER_MARK  # noqa: E402

ENV_FILE = "config.env"
ENV_EXAMPLE = "config.env.example"
PROFILE_FILE = "skill_profile.txt"

# 向导会逐项询问的键 -> 提示文案 / 是否必填
SMTP_PRESETS = {
    "qq": ("smtp.qq.com", "465"),
    "163": ("smtp.163.com", "465"),
    "gmail": ("smtp.gmail.com", "465"),
    "outlook": ("smtp.office365.com", "587"),
    "exmail": ("smtp.exmail.qq.com", "465"),
}


def quote_value(value: str) -> str:
    """值含空白 / # / 引号时加双引号，与 parse_env_file 兼容。"""
    if re.search(r'[\s#"\'\\]', value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def load_lines(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.readlines()


def save_lines(path: str, lines: list) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def parse_values(lines: list) -> dict:
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values


def upsert(lines: list, key: str, value: str) -> list:
    """更新或追加 KEY=VALUE，保留原文件注释与顺序。"""
    new_line = f"{key}={quote_value(value)}\n"
    for i, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            lines[i] = new_line
            return lines
    lines.append(new_line)  # 找不到则追加到末尾（会被合并读取，无影响）
    return lines


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    if default:
        hint = "******" if secret else default
        text = input(f"{prompt}  [当前: {hint}] 直接回车保持不变 > ").strip()
    else:
        text = input(f"{prompt}  > ").strip()
    if not text and default:
        return default
    return text


def main() -> int:
    print("=" * 60)
    print("daily-job-digest 初始化向导")
    print("(只读写本目录 config.env / skill_profile.txt，均不会提交到 git)")
    print("=" * 60)

    # 1) 确保两个模板文件存在
    if not os.path.exists(ENV_FILE):
        if os.path.exists(ENV_EXAMPLE):
            import shutil
            shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
            print(f"\n[1/4] 已生成 {ENV_FILE}（从模板复制，可直接编辑）")
        else:
            print(f"\n[1/4] 缺少 {ENV_EXAMPLE}，请确认在项目根目录运行本脚本")
            return 1
    else:
        print(f"\n[1/4] {ENV_FILE} 已存在，保留（不会覆盖）")

    if not os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            f.write(GUIDED_PROFILE_TEMPLATE)
        print(f"[2/4] 已生成 {PROFILE_FILE}（空白引导模板，请填写你的真实背景）")
    else:
        print(f"[2/4] {PROFILE_FILE} 已存在，保留（不会覆盖）")

    # 2) 逐项询问填写
    lines = load_lines(ENV_FILE)
    values = parse_values(lines)
    print("\n[3/4] 请逐项填写（没有则直接回车保留当前值）")
    print("      · DeepSeek API Key： https://platform.deepseek.com 创建")
    print("      · SMTP_PASS 填【授权码/应用专用密码】，不是邮箱登录密码")

    key = ask("DeepSeek API Key", values.get("DEEPSEEK_API_KEY", ""), secret=True)
    if key:
        upsert(lines, "DEEPSEEK_API_KEY", key)

    preset = input("发件邮箱类型 qq/163/gmail/outlook/exmail/其他 [qq] > ").strip().lower() or "qq"
    if preset in SMTP_PRESETS:
        host, port = SMTP_PRESETS[preset]
        print(f"   -> 使用 {host}:{port}")
        upsert(lines, "SMTP_HOST", host)
        upsert(lines, "SMTP_PORT", port)
    else:
        host = input("SMTP 服务器地址 > ").strip()
        port = input("SMTP 端口（465=SSL，587/25=STARTTLS）> ").strip()
        if host:
            upsert(lines, "SMTP_HOST", host)
        if port:
            upsert(lines, "SMTP_PORT", port)

    smtp_user = ask("发件邮箱地址 (SMTP_USER)", values.get("SMTP_USER", ""))
    if smtp_user:
        upsert(lines, "SMTP_USER", smtp_user)
    smtp_pass = ask("授权码/应用专用密码 (SMTP_PASS)", values.get("SMTP_PASS", ""), secret=True)
    if smtp_pass:
        upsert(lines, "SMTP_PASS", smtp_pass)
    mail_to = ask("收件人邮箱（多个用英文逗号分隔）", values.get("MAIL_TO", ""))
    if mail_to:
        upsert(lines, "MAIL_TO", mail_to)

    tags = ask("搜索标签（技术栈，逗号分隔；RemoteOK/Jobicy 等按此抓取）",
               values.get("REMOTEOK_TAGS", ""))
    if tags:
        upsert(lines, "REMOTEOK_TAGS", tags)

    save_lines(ENV_FILE, lines)
    print("\n[4/4] 已保存 " + ENV_FILE)

    # 3) 校验必填项
    values = parse_values(load_lines(ENV_FILE))
    missing = [k for k in ("DEEPSEEK_API_KEY", "SMTP_USER", "SMTP_PASS", "MAIL_TO")
               if not values.get(k)]
    if missing:
        print("\n⚠ 以下必填项仍为空，请手动编辑 config.env 补齐：")
        for m in missing:
            print(f"   - {m}")
        return 1

    print(f"\n✓ 配置基本就绪。记得打开 {PROFILE_FILE} 填写你的【真实】背景"
          f"（删除含「{PROFILE_PLACEHOLDER_MARK}」的占位行）。")

    # 4) 可选试跑
    try:
        if input("\n现在试跑一次（--dry-run，不发送邮件，但会调用 DeepSeek 产生少量费用）？[y/N] > ").strip().lower() == "y":
            subprocess.call([sys.executable, "daily_job_digest.py", "--dry-run"])
    except EOFError:  # 非交互环境（如 CI）直接跳过
        pass
    print("\n完成。需要每天自动推送，见 README「三、定时任务」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
