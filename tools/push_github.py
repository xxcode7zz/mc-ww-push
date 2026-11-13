"""把本地仓库推到 GitHub —— 首次上传 / 后续补推都用它。

为什么单独一个脚本，而不是让人手打 ``git push https://token@...``：

* **令牌不进 argv**。URL 里带令牌会被 ``ps`` / 进程列表 / shell 历史看到。
  这里改用 ``http.extraheader`` 走环境变量传，进程列表里看不到明文。
* **令牌不落盘**。不写 ``.git/config``、不写 ``.git-credentials``、不写
  ``.netrc``。``origin`` 只存干净的地址，后续凭据交给 Git Credential Manager。
* **令牌不回显**。交互输入走 ``getpass``，日志里一律打码。
* **仓库不存在就代建**。用同一个令牌调 REST ``POST /user/repos``，
  省掉「先去网页手动建一个空仓库」这一步。

用法（在项目根目录）::

    python tools/push_github.py https://github.com/你的用户名/mc-ww

    然后按提示输入用户名和令牌（令牌输入时不显示）。
    Personal Access Token 需要 ``repo`` 权限（经典）或
    ``Administration: Read and write`` + ``Contents: Read and write``（细粒度）。

也支持从环境变量读，方便已经设好的机器::

    $env:MC_WW_GITHUB_TOKEN = "..."
    python tools/push_github.py <地址> --user 你的用户名

也支持从文件读（用于无法交互输入的场合，比如由别的程序代为执行）::

    python tools/push_github.py <地址> --token-file D:\\temp\\pat.txt

    文件里只放令牌本身，前后的空白和换行会被忽略。用完后请自行删除。
    注意：令牌文件**不要**放在仓库目录内，否则有被误提交的风险。

只推分支（不发版）是默认行为；要连 tag 一起推加 ``--tags``。
想先只建仓库不推，或推一个已建好的仓库跳过建仓，用 ``--no-create``。
"""

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_ENV = "MC_WW_GITHUB_TOKEN"
API = "https://api.github.com"

# 本次实际使用的令牌。mask() 读这里而不是只读环境变量 ——
# 交互输入的令牌不在 os.environ 里，只读环境变量会漏打码。
_ACTIVE_TOKEN = ""


def mask(text):
    """把可能出现的令牌全部打码 —— 这个脚本的输出可能被截图。"""
    for token in (_ACTIVE_TOKEN, os.environ.get(TOKEN_ENV) or ""):
        if token and len(token) >= 8:
            text = text.replace(token, "***")
    return text


def api(method, path, token, payload=None):
    """打一次 GitHub REST。返回 ``(status, body_dict)``，不抛 HTTP 异常。

    把 4xx 也当正常返回值，是为了能在调用处按状态码给出可操作的提示，
    而不是丢一个裸 traceback 给用户。
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "mc-ww-push")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"message": raw[:300]}
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上 api.github.com：{exc.reason}")


def git(args, env=None, capture=True, timeout=300):
    """跑一条 git 命令；失败抛 SystemExit 并带上打码后的输出。"""
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, env=env, text=True,
            capture_output=capture, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"git {' '.join(args)} 超时（{timeout}s）—— 网络不通或被墙。")
    # 退出码必须在两种模式下都检查。capture=False 时输出已经流到终端，
    # 早先漏检导致「推送失败却打印完成」，这里一并修正。
    if result.returncode != 0:
        detail = mask((result.stderr or result.stdout or "").strip()) if capture else ""
        if detail:
            raise SystemExit(f"git {' '.join(args)} 失败：\n{detail}")
        raise SystemExit(f"git {' '.join(args)} 失败（退出码 {result.returncode}），详见上面的输出。")
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


def split_repo(url):
    """从 ``https://github.com/<owner>/<repo>.git`` 取 owner 与 repo 名。"""
    bare = url[:-4] if url.endswith(".git") else url
    parts = bare.rstrip("/").split("/")
    if len(parts) < 2 or not parts[-1] or not parts[-2]:
        raise SystemExit(f"地址 {url} 里看不出 owner/repo，请检查。")
    return parts[-2], parts[-1]


def ensure_repo(owner, name, token, private, description):
    """仓库不存在就用令牌建一个空仓库。返回 'exists' / 'created'。"""
    status, info = api("GET", f"/repos/{owner}/{name}", token)
    if status == 200:
        print(f"仓库已存在：{info.get('full_name')}（{'私有' if info.get('private') else '公开'}）")
        return "exists"
    if status != 404:
        raise SystemExit(f"查询仓库失败（HTTP {status}）：{info.get('message')}")

    # 建在个人账号下还是组织下，取决于 owner 是不是令牌本人
    me_status, me = api("GET", "/user", token)
    login = me.get("login", "") if me_status == 200 else ""
    path = "/user/repos" if (not login or owner.lower() == login.lower()) else f"/orgs/{owner}/repos"

    payload = {"name": name, "private": private, "auto_init": False,
               "has_issues": True, "has_wiki": False}
    if description:
        payload["description"] = description

    status, info = api("POST", path, token, payload)
    if status in (200, 201):
        print(f"已创建仓库：{info.get('full_name')} → {info.get('html_url')}")
        return "created"

    message = info.get("message") or ""
    hint = ""
    if "not accessible by integration" in message:
        hint = (
            "\n这是 GitHub App 的令牌：权限集由 App 注册方固定，用户无法添加 Administration。\n"
            "改用你自己的 Personal Access Token（经典 PAT 勾 repo 即可）。")
    elif status == 403:
        hint = (
            "\n令牌缺少建仓权限。经典 PAT 需要勾选 `repo`；"
            "细粒度 PAT 需要 `Administration: Read and write`。")
    elif status == 422:
        hint = "\n仓库名可能已被占用，或 owner 下不允许创建。"
    raise SystemExit(f"创建仓库失败（HTTP {status}）：{message}{hint}")


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


def token_scopes(token):
    """读令牌的 OAuth scope（GitHub 在响应头 X-OAuth-Scopes 里返回）。

    经典 PAT 才有这个头；细粒度 PAT（github_pat_ 前缀）没有，返回空集合，
    此时不当作结论，只是跳过预检。
    """
    req = urllib.request.Request(API + "/user", method="GET")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "mc-ww-push")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.headers.get("X-OAuth-Scopes") or ""
            return {s.strip() for s in raw.split(",") if s.strip()}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SystemExit("令牌无效或已过期（HTTP 401），请重新生成。")
        return set()
    except urllib.error.URLError as exc:
        raise SystemExit(f"连不上 api.github.com：{exc.reason}")


def workflow_files_to_push():
    """列出将要推送的 workflow 文件（GitHub 对这类文件要求额外 scope）。"""
    result = subprocess.run(["git", "ls-files", ".github/workflows"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def preflight(token):
    """推送前把「注定会失败」的条件挑出来，省掉一轮白跑。"""
    files = workflow_files_to_push()
    if not files:
        return
    scopes = token_scopes(token)
    if not scopes:
        # 细粒度令牌没有 scope 头，无法判断，交给 GitHub 自己裁决
        return
    if "workflow" in scopes:
        return
    shown = "\n".join(f"  - {f}" for f in files)
    raise SystemExit(
        "令牌缺少 `workflow` scope，这次推送会被 GitHub 拒绝。\n"
        f"仓库里有这些 workflow 文件：\n{shown}\n\n"
        "GitHub 的规则：通过 API/HTTPS 推送修改 `.github/workflows/*` 必须持有\n"
        "`workflow` scope，这是独立于 `repo` 之外的一项，仅勾 `repo` 不够。\n\n"
        "两个解法，任选其一：\n"
        "  1. 给现有令牌补权限：https://github.com/settings/tokens → 点该令牌 →\n"
        "     勾上 `workflow` → Update token。令牌字符串不变，不用改任何配置。\n"
        "  2. 重新生成一个同时勾 `repo` + `workflow` 的令牌。\n\n"
        f"当前令牌 scope：{', '.join(sorted(scopes))}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把本地仓库推到 GitHub（令牌不进 argv、不落盘，仓库不存在则代建）")
    parser.add_argument("url", help="仓库地址，如 https://github.com/你/mc-ww")
    parser.add_argument("--user", default="", help="GitHub 用户名（默认取地址里的那段）")
    parser.add_argument("--branch", default="", help="要推的分支（默认为当前分支）")
    parser.add_argument("--tags", action="store_true", help="连本地 tag 一起推")
    parser.add_argument("--no-create", action="store_true",
                        help="不代建仓库（目标仓库必须已存在）")
    parser.add_argument("--public", action="store_true", help="建为公开仓库（默认私有）")
    parser.add_argument("--description", default="", help="建仓时写入的仓库简介")
    parser.add_argument("--token-file", default="",
                        help="从文件读令牌（文件内只放令牌，用完请删除）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的步骤")
    args = parser.parse_args(argv)

    if not (ROOT / ".git").exists():
        raise SystemExit(f"{ROOT} 不是 git 仓库。")

    url = normalize(args.url)
    branch = args.branch or current_branch()
    owner, repo = split_repo(url)
    username = args.user or owner

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
        if not args.no_create:
            print(f"  GET  /repos/{owner}/{repo}      （探活，404 则建仓）")
            print(f"  POST /user/repos                （建 {'公开' if args.public else '私有'}仓库 {repo}）")
        print(f"  git remote add origin {url}   （若已存在则 set-url）")
        print(f"  git push -u origin {branch}")
        if args.tags:
            print("  git push origin --tags")
        return 0

    # 令牌：优先 --token-file，其次环境变量，最后交互输入（不回显、不进历史）
    token = ""
    if args.token_file:
        path = Path(args.token_file).expanduser()
        if not path.is_file():
            raise SystemExit(f"令牌文件不存在：{path}")
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit(f"令牌文件是空的：{path}")
        # 只提示「读了什么」，不打印内容；长度也打码，避免泄露指纹
        print(f"\n已从文件读取令牌：{path.name}")
    if not token:
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

    if not args.dry_run:
        preflight(token)

    if args.no_create:
        print("\n已跳过建仓（--no-create）")
    else:
        print("\n检查仓库是否存在 …")
        ensure_repo(owner, repo, token, private=not args.public,
                    description=args.description)

    # origin 存**不带令牌**的干净地址；后续凭据由 GCM 管理
    has_origin = subprocess.run(["git", "remote", "get-url", "origin"],
                                cwd=ROOT, capture_output=True, text=True)
    if has_origin.returncode == 0:
        git(["remote", "set-url", "origin", url])
        print(f"\n已更新 origin → {url}")
    else:
        git(["remote", "add", "origin", url])
        print(f"\n已添加 origin → {url}")

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
