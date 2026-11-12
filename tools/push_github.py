"""把本地仓库推到 GitHub —— 首次上传 / 后续补推都用它。

为什么单独一个脚本，而不是让人手打 ``git push https://token@...``：

* **令牌不进 argv**。URL 里带令牌会被 ``ps`` / 进程列表 / shell 历史看到。
  这里改用 ``http.extraheader`` 走环境变量传，进程列表里看不到明文。
* **令牌不落盘**。不写 ``.git/config``、不写 ``.git-credentials``、不写
  ``.netrc``。``origin`` 只存干净的地址，后续凭据交给 Git Credential Manager。
* **令牌不回显**。交互输入走 ``getpass``，日志里一律打码。

用法（在项目根目录）::

    python tools/push_github.py https://github.com/你的用户名/mc-ww

    然后按提示输入用户名和令牌（令牌输入时不显示）。
    Personal Access Token 需要 ``repo`` 权限（经典）或 ``Contents: Read and write``
    （细粒度）。

也支持从环境变量读，方便已经设好的机器::

    $env:MC_WW_GITHUB_TOKEN = "..."
    python tools/push_github.py <地址> --user 你的用户名

只推分支（不发版）是默认行为；要连 tag 一起推加 ``--tags``。
"""

import argparse
import base64
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_ENV = "MC_WW_GITHUB_TOKEN"

# 本次实际使用的令牌。mask() 读这里而不是只读环境变量 ——
# 交互输入的令牌不在 os.environ 里，只读环境变量会漏打码。
_ACTIVE_TOKEN = ""


def mask(text):
    """把可能出现的令牌全部打码 —— 这个脚本的输出可能被截图。"""
    for token in (_ACTIVE_TOKEN, os.environ.get(TOKEN_ENV) or ""):
        if token and len(token) >= 8:
            text = text.replace(token, "***")
    return text


def git(args, env=None, capture=True, timeout=300):
    """跑一条 git 命令；失败抛 SystemExit 并带上打码后的输出。"""
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, env=env, text=True,
            capture_output=capture, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"git {' '.join(args)} 超时（{timeout}s）—— 网络不通或被墙。")
    if capture and result.returncode != 0:
        detail = mask((result.stderr or result.stdout or "").strip())
        raise SystemExit(f"git {' '.join(args)} 失败：\n{detail}")
    return result


def normalize(url):
    """补 .git、去空白。GitHub 两种写法（带不带 .git）都能用，统一成一种。"""
    url = url.strip().rstrip("/")
    if not url:
        raise SystemExit("仓库地址不能为空。")
    if not url.startswith(("https://", "http://")):
        raise SystemExit(
            f"地址 {url} 不是 https 形式。\n"
            "GitHub 已不支持 SSH 之外的密码推送走 SSH 端口，请用 https://github.com/... 形式。")
    if not url.endswith(".git"):
        url += ".git"
    return url


def auth_env(token, username):
    """用环境变量传认证头，避免令牌出现在命令行参数里。

    GitHub 的 git-over-HTTPS 接受任意非空用户名配令牌作密码；约定用
    ``x-access-token``。用 ``GIT_CONFIG_COUNT`` 注入，比 ``-c`` 安全：
    ``-c`` 的键值会进 argv。
    """
    raw = f"{username}:{token}".encode()
    header = "Authorization: basic " + base64.b64encode(raw).decode()
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = header
    # 万一本机有凭据助手，也别让它在推送途中弹窗打断脚本
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def current_branch():
    result = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("当前处于游离 HEAD 状态，无法确定要推哪个分支。")
    return result.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把本地仓库推到 GitHub（令牌不进 argv、不落盘）")
    parser.add_argument("url", help="仓库地址，如 https://github.com/你/mc-ww")
    parser.add_argument("--user", default="", help="GitHub 用户名（默认取地址里的那段）")
    parser.add_argument("--branch", default="", help="要推的分支（默认为当前分支）")
    parser.add_argument("--tags", action="store_true", help="连本地 tag 一起推")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的步骤")
    args = parser.parse_args(argv)

    if not (ROOT / ".git").exists():
        raise SystemExit(f"{ROOT} 不是 git 仓库。")

    url = normalize(args.url)
    branch = args.branch or current_branch()

    # 用户名的默认值从地址里猜：https://github.com/<owner>/<repo>.git
    username = args.user
    if not username:
        parts = url.rstrip(".git").rstrip("/").split("/")
        if len(parts) >= 2:
            username = parts[-2]
        if not username:
            raise SystemExit("猜不出用户名，请用 --user 指定。")

    print(f"仓库：{url}")
    print(f"分支：{branch}")
    print(f"用户：{username}")

    commits = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True)
    if commits.returncode != 0:
        raise SystemExit("本地还没有任何提交 —— 先 git add / git commit。")
    print(f"提交：{commits.stdout.strip()} 个")

    tags = subprocess.run(["git", "tag", "--list"], cwd=ROOT,
                          capture_output=True, text=True).stdout.split()
    if tags:
        print(f"tag ：{', '.join(tags)}" + ("" if args.tags else "（未指定 --tags，不发版"))

    if args.dry_run:
        print("\n--- 演练，将执行 ---")
        print(f"  git remote add origin {url}   （若已存在则 set-url）")
        print(f"  git push -u origin {branch}")
        if args.tags:
            print("  git push origin --tags")
        return 0

    # 令牌：优先环境变量，否则交互输入（不回显、不进历史）
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print()
        token = getpass.getpass(f"粘贴 GitHub Personal Access Token（输入不回显，"
                               f"也可设 {TOKEN_ENV} 环境变量）: ").strip()
    if not token:
        raise SystemExit("没有提供令牌，已取消。")

    global _ACTIVE_TOKEN
    _ACTIVE_TOKEN = token
    env = auth_env(token, username)

    # origin 存**不带令牌**的干净地址；后续凭据由 GCM 管理
    has_origin = subprocess.run(["git", "remote", "get-url", "origin"],
                                cwd=ROOT, capture_output=True, text=True)
    if has_origin.returncode == 0:
        git(["remote", "set-url", "origin", url])
        print(f"已更新 origin → {url}")
    else:
        git(["remote", "add", "origin", url])
        print(f"已添加 origin → {url}")

    print(f"\n推送分支 {branch} …")
    git(["push", "-u", "origin", branch], env=env, capture=False, timeout=600)
    print("分支推送完成")

    if args.tags:
        print("\n推送 tag …")
        git(["push", "origin", "--tags"], env=env, capture=False, timeout=600)
        print("tag 推送完成 —— GitHub Actions 会自动发版（见 .github/workflows/release.yml）")

    print("\n完成。仓库地址：" + url.removesuffix(".git"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
