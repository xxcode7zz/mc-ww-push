"""把 MC-WW 发布到 CNB（国内优先）与 GitHub（保底）。

**这不是「上游同步」**。同步是拉 ok-ww 源码（见 ``mcww/sync_engine.py``），
本脚本是发布**我们自己的**版本：给当前提交打一个版本 tag，推到两个远端。

一个 tag = 一个可安装版本。pyappify 会把该 tag 的整棵工作树拉下来覆盖安装，
所以 tag 内容必须就是当前 ``main`` 分支的内容，否则用户装到的和源码不一致。

用法：

    python tools/publish.py --dry-run            # 演练：检查 + 打印要执行的命令
    python tools/publish.py v1.0.0               # 打 tag 并推送（CNB 优先，失败退 GitHub）
    python tools/publish.py v1.0.0 --only cnb    # 只推 CNB
    python tools/publish.py v1.0.0 --skip-checks # 跳过发布前检查（不建议）
    python tools/publish.py --list               # 看已有 tag 与远端状态

**令牌只从环境变量读**，绝不落盘、绝不打印：

===================  ===================================================
``MC_WW_CNB_TOKEN``      CNB 访问令牌（用户名固定为 ``cnb``）
``MC_WW_GITHUB_TOKEN``   GitHub Personal Access Token（需要 ``repo`` 权限）
===================  ===================================================

CNB 令牌在「设置 → 访问令牌」生成，可限定只读/读写并可随时撤销。
GitHub 令牌在 Settings → Developer settings → Personal access tokens 生成。
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 同级脚本直接按名字导入（tools/ 不是包，本脚本运行时它已在 sys.path[0]，
# 但从别处 import 时不一定，所以显式补一次）
sys.path.insert(0, str(Path(__file__).resolve().parent))

VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:(-|\.)(alpha|beta|rc)(?:\.(\d+))?)?$")

# 通道 -> (令牌环境变量, 认证用户名)
CHANNEL_AUTH = {
    "cnb": ("MC_WW_CNB_TOKEN", "cnb"),
    "github": ("MC_WW_GITHUB_TOKEN", ""),
}


def _git(*args, check=True, capture=True, env=None, timeout=60):
    """跑一条 git 命令。``env`` 用来临时注入令牌，避免写进任何配置文件。

    ``timeout`` 是必需的：GitHub 的 git 协议在国内经常是「连不上也不断开」，
    没有超时就会一直挂着，把整个脚本卡死。
    """
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=capture, text=True,
            timeout=timeout, env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"git {' '.join(args)} 超过 {timeout}s 没响应 —— 该通道基本不可达，"
            "换另一个通道或检查网络。")
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"git {' '.join(args)} 失败：\n{detail}")
    return result


def _auth_url(url: str, token: str, username: str) -> str:
    """把令牌嵌进推送地址。只在内存里拼，不写 remote、不写 credential 文件。"""
    scheme, rest = url.split("://", 1)
    prefix = f"{username}:{token}@" if username else f"{token}@"
    return f"{scheme}://{prefix}{rest}"


def _mask(text: str, tokens: list) -> str:
    for token in tokens:
        if token:
            text = text.replace(token, "***")
    return text


def _channels():
    from mcww import release
    return release.configured_channels()


def _token_for(channel: str):
    env_name, username = CHANNEL_AUTH[channel]
    token = os.environ.get(env_name, "").strip()
    return token, username, env_name


# ---------------------------------------------------------------- 子命令


def cmd_list():
    from mcww import release

    tags = _git("tag", "--list", "--sort=-v:refname", check=False).stdout.split()
    if tags:
        print("本地 tag（新→旧，最多 10 个）：")
        for tag in tags[:10]:
            print(f"  {tag}")
    else:
        print("本地还没有任何 tag —— 一次都没发布过。")

    print("\n发布通道：")
    channels = _channels()
    if not channels:
        print("  (无) 先跑 python tools/set_repo.py --cnb <地址> --github <地址>")
        return 0
    for channel, url in channels:
        token, _, env_name = _token_for(channel)
        state = "令牌已设置" if token else f"缺少 {env_name}"
        print(f"  {release.CHANNEL_LABELS.get(channel, channel):8s} {url}  [{state}]")

    print("\n远端引用（能读到多少看网络与权限）：")
    for channel, url in channels:
        token, username, _ = _token_for(channel)
        probe = _auth_url(url, token, username) if token else url
        try:
            result = _git("ls-remote", "--tags", probe, check=False, timeout=20,
                          env={"GIT_TERMINAL_PROMPT": "0"})
        except SystemExit as exc:
            print(f"  {channel}: 探测超时 —— 20s 内无响应，该通道不可用（{exc}）")
            continue
        if result.returncode == 0:
            count = len([l for l in result.stdout.splitlines() if l.strip()])
            print(f"  {channel}: 可达，{count} 个远端 tag")
        else:
            lines = (result.stderr or "").strip().splitlines()
            reason = lines[-1] if lines else "未知原因"
            print(f"  {channel}: 读不到 —— {_mask(reason, [token])}")
    return 0


def cmd_dry_run(tag):
    """只演练：跑检查、算好命令，不碰仓库、不推。"""
    from mcww import release

    print("=== 1/3 发布前检查 ===")
    import check_release
    check_release.run_checks(tag)
    code = check_release.report()
    if code != 0:
        print("\n检查未通过，演练终止（真发布也会被同样拦下）。")
        return code
    if not tag:
        print("\n（未指定 tag，跳过打 tag 演练）")
        return 0

    print(f"\n=== 2/3 将要执行的步骤（tag={tag}）===")
    channels = _channels()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    branch = branch if branch and branch != "HEAD" else "main"
    print(f"  git tag -a {tag} -m \"MC-WW {tag}\"")
    for index, (channel, url) in enumerate(channels):
        token, username, env_name = _token_for(channel)
        # 演练输出里也要打码：终端可能被截图分享，令牌不该出现在任何日志里
        shown = _auth_url(url, "***", username) if token else url
        if token:
            note = ""
        elif index < len(channels) - 1:
            note = f"   ← 缺 {env_name}，这一步会跳过并降级到下一个通道"
        else:
            note = f"   ← 缺 {env_name}，最后一个通道也缺令牌，发布会失败"
        # 每个远端都要先推分支、再推 tag（不同仓库，不能只推一次）
        print(f"  git push {shown} {branch}   # 分支，让远端仓库先有内容")
        print(f"  git push {shown} {tag}{note}")
    print("\n=== 3/3 没做的事 ===")
    print("  没有创建 tag、没有联网、没有上传任何东西。")
    print(f"  真发布：python tools/publish.py {tag}")
    return 0


def cmd_publish(tag, only="", skip_checks=False):
    from mcww import release

    if not VERSION_RE.match(tag):
        raise SystemExit(
            f"版本号 {tag!r} 不合规。pyappify 只认 v1.2.3 或 v1.2.3-beta.1 这种格式，"
            "别的 tag 不会出现在更新列表里，用户永远升不到。")

    if not skip_checks:
        print("=== 发布前检查 ===")
        import check_release
        check_release.run_checks(tag)
        if check_release.report() != 0:
            raise SystemExit("检查未通过，已中止（确实要跳：--skip-checks）")

    # tag 已存在但内容不同 = 覆盖发布，会让已装用户下的版本对不上
    existing = _git("tag", "--list", tag, check=False).stdout.strip()
    if existing:
        target = _git("rev-parse", f"{tag}^{{commit}}", check=False).stdout.strip()
        head = _git("rev-parse", "HEAD", check=False).stdout.strip()
        if target != head:
            raise SystemExit(
                f"tag {tag} 已存在且指向 {target[:8]}，不是当前 HEAD {head[:8]}。\n"
                "覆盖已发布版本会让已装用户的更新链断掉。请用新版本号，"
                f"或确需重发则先 git tag -d {tag}删掉旧的。")
        print(f"tag {tag} 已存在且指向当前 HEAD，只补推送。")

    branch = _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()

    print("\n=== 推送 ===")
    channels = [(c, u) for c, u in _channels()
                if not only or c == only]
    if not channels:
        raise SystemExit(f"没有可用通道{'（--only ' + only + ' 未配置）' if only else ''}。"
                         "先跑 python tools/set_repo.py --cnb <地址> --github <地址>")

    if not existing:
        _git("tag", "-a", tag, "-m", f"MC-WW {tag}")
        print(f"✓ 已创建 tag {tag}")

    pushed = []
    failed = []
    tokens = {}
    for channel, url in channels:
        token, username, env_name = _token_for(channel)
        label = release.CHANNEL_LABELS.get(channel, channel)
        tokens[channel] = token
        if not token:
            failed.append((channel, f"缺少环境变量 {env_name}"))
            print(f"· {label}: 跳过（没有 {env_name}）")
            continue
        auth = _auth_url(url, token, username)
        # 先推分支（让仓库有内容），再推 tag（pyappify 只认 tag）
        args = [auth]
        if branch and branch != "HEAD":
            args = [auth, branch]
        result = _git("push", "--quiet", *args, check=False,
                      env={"GIT_TERMINAL_PROMPT": "0"})
        if result.returncode != 0:
            reason = _mask((result.stderr or result.stdout or "").strip(), [token])
            failed.append((channel, reason))
            print(f"✗ {label}: 推送失败 —— {reason.splitlines()[-1] if reason else '未知原因'}")
            continue
        result = _git("push", "--quiet", auth, tag, check=False,
                      env={"GIT_TERMINAL_PROMPT": "0"})
        if result.returncode != 0:
            reason = _mask((result.stderr or result.stdout or "").strip(), [token])
            failed.append((channel, reason))
            print(f"✗ {label}: tag 推送失败 —— {reason.splitlines()[-1] if reason else '未知原因'}")
            continue
        pushed.append(channel)
        print(f"✓ {label}: 已推送 {branch or 'HEAD'} 与 {tag}")

    print("\n=== 结果 ===")
    all_tokens = list(tokens.values())
    if pushed:
        first = pushed[0]
        url = dict(channels)[first]
        print(f"主通道：{release.CHANNEL_LABELS.get(first, first)}")
        base = url[:-4] if url.endswith(".git") else url
        if first == "cnb":
            print(f"  发布页：{base}/-/releases/tag/{tag}")
            print(f"  克隆  ：{url}")
        else:
            print(f"  发布页：{base}/releases/tag/{tag}")
        if len(pushed) > 1:
            print(f"镜像通道：{', '.join(release.CHANNEL_LABELS.get(c, c) for c in pushed[1:])}")
    else:
        print("✗ 一个通道都没推成功。")
        for channel, reason in failed:
            print(f"  {release.CHANNEL_LABELS.get(channel, channel)}: {_mask(reason, all_tokens)}")
        return 1

    if failed:
        print("\n未成功的通道：")
        for channel, reason in failed:
            print(f"  {release.CHANNEL_LABELS.get(channel, channel)}: {_mask(reason, all_tokens)}")
        if "cnb" not in pushed:
            print("  ! 国内主通道没推成功 —— 国内用户会退回 GitHub，速度可能很差。")

    print("\n接下来：")
    print("  · 在网页上确认 Release 页出现新版本")
    print(f"  · python tools/publish.py --list   # 复查两个远端 tag")
    print("  · 客户端「关于页 → 检查更新」应能看到该版本")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="发布 MC-WW 新版本（CNB 国内优先，GitHub 保底）")
    parser.add_argument("tag", nargs="?", default="", help="版本 tag，例如 v1.0.0")
    parser.add_argument("--dry-run", action="store_true", help="只检查和打印命令，不实际发布")
    parser.add_argument("--list", action="store_true", help="列出 tag 与通道状态")
    parser.add_argument("--only", default="", choices=["", "cnb", "github"],
                        help="只推某个通道")
    parser.add_argument("--skip-checks", action="store_true", help="跳过发布前检查")
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list()
    if args.dry_run:
        return cmd_dry_run(args.tag)
    if not args.tag:
        parser.print_help()
        print("\n提示：先 --dry-run 演练一次，看清要执行的命令再真发布。")
        return 2
    return cmd_publish(args.tag, args.only, args.skip_checks)


if __name__ == "__main__":
    raise SystemExit(main())
