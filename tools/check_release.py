"""发布前检查：能不能打这个 tag / 这个提交能不能进流水线。

被三个地方调用：

* ``tools/publish.py``     —— 打 tag 之前跑一遍，不合格就不打；
* CNB 流水线 ``.cnb.yml``  —— push 时跑，拦住"带病提交"；
* GitHub Actions ``.github/workflows/`` —— 与 CNB 等价的保底通道；
* 手工排查                —— ``python tools/check_release.py``。

**只做静态检查，不 import 应用本体**（不碰 PySide6、不初始化 ok 框架），
所以能在 ``python:3.12-slim`` 这样的裸镜像里跑 —— 流水线正需要这一点。

检查分三档：

============  ==========================================================
硬错误        会让安装包拉错仓库 / 变回 ok-ww / 更新链断裂，必须修
警告          能出包但体验会退化（缺图标、版本号没对、工作树不干净）
提示          仅供参考（体积、通道配置）
============  ==========================================================

退出码：``0`` 通过（可能带警告）；``1`` 有硬错误。
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# pyappify 认的版本格式，和 pyappify/versions.py 的 version_tag_key 保持一致
VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:(-|\.)(alpha|beta|rc)(?:\.(\d+))?)?$")

# AboutTab.LINKS 里有、我们真正想用的键。写在这里而不是 import，
# 是为了在裸镜像里也能校验（import AboutTab 会拉起整个 Qt 依赖树）。
KNOWN_LINK_KEYS = frozenset({
    "github", "download", "discord", "qq_group", "qq_channel",
    "faq", "share", "sponsor",
})

errors = []
warnings = []
notes = []


def error(message):
    errors.append(message)


def warn(message):
    warnings.append(message)


def note(message):
    notes.append(message)


def _read(rel):
    try:
        return (ROOT / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _pyappify_urls():
    """从 pyappify.yml 里取 (profile 名, git_url)，顺序保持文件里的顺序。"""
    urls = []
    current = ""
    for line in _read("pyappify.yml").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        name_match = re.match(r'- name:\s*"([^"]+)"', stripped)
        if name_match:
            current = name_match.group(1)
            continue
        url_match = re.match(r'git_url:\s*"([^"]*)"', stripped)
        if url_match:
            urls.append((current, url_match.group(1).strip()))
    return urls


def _literal_assignments(rel, names):
    """只用 AST 取模块顶层的字符串常量，不执行模块。

    ``branding.py`` 顶层的 ``release.repo_url(...)`` 需要读配置，在线下不可用；
    真值另有校验途径（config 检查），这里只取静态字面量做交叉验证。
    """
    found = {}
    try:
        tree = ast.parse(_read(rel))
    except SyntaxError as exc:
        error(f"{rel} 语法错误：{exc}")
        return found
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                found[target.id] = node.value.value
    return found


# ---------------------------------------------------------------- 单项检查


def check_channels(required=True):
    """双通道配置：至少配一个，且 profile 绑定符合分工。

    ``required=False``（push 阶段）时，未配置只算警告 —— 否则仓库刚建好、
    地址还没填的那段时间，每次 push 都是红的，反而让人去关掉检查。
    真到发版（``--tag``）才升级成硬错误。
    """
    from mcww import release

    channels = release.configured_channels()
    if not channels:
        message = ("没有配置任何发布通道 —— 安装包会去拉一个不存在的仓库。"
                   "先跑 `python tools/set_repo.py --cnb <地址> --github <地址>`。")
        if required:
            error(message)
        else:
            warn(message + "（普通 push 不阻断，发版时会拦）")
        return

    for channel, url in channels:
        label = release.CHANNEL_LABELS.get(channel, channel)
        note(f"{label} 通道已配置：{url}")

    if len(channels) == 1:
        only = channels[0][0]
        if only == "cnb":
            warn("只配了 CNB：海外用户走 GitHub profile 时会回退到 CNB，"
                 "国内可用但海外可能很慢。建议补一个 GitHub 仓库做保底。")
        else:
            warn("只配了 GitHub：国内下载可能很慢或拉不动。"
                 "建议补一个 CNB 仓库做国内镜像。")
    elif [c for c, _ in channels] != list(release.CHANNEL_ORDER):
        error(f"通道顺序异常：{channels}，期望 CNB 在 GitHub 之前。")

    for issue in release.profile_binding_issues():
        error(f"pyappify.yml 绑定错误：{issue}。")


def check_git_url_stale(required=True):
    """pyappify.yml 里不能残留上游仓库地址，也不能为空。

    "为空" 只在发版时算错：仓库刚建、地址没填的阶段，push 检查不该红。
    """
    profiles = _pyappify_urls()
    if not profiles:
        error("pyappify.yml 里找不到任何 profile（打包器会直接失败）。")
        return
    for profile, url in profiles:
        if not url:
            message = f'profile "{profile}" 的 git_url 为空。'
            if required:
                error(message)
            else:
                warn(message + "（发版前需执行 tools/set_repo.py 写入）")
        elif "ok-oldking" in url:
            error(f'profile "{profile}" 仍指向上游 ok-ww 仓库 —— '
                  "装完会变回纯 ok-ww，MC-WW 的品牌层全被覆盖。")


def check_branding_static():
    """branding.py 的静态常量：应用标识没被改回 ok-ww、链接键合法。"""
    literals = _literal_assignments(
        "mcww/branding.py", {"APP_NAME", "APP_ID", "APP_VERSION", "LINK_KEYS"})

    if literals.get("APP_NAME") != "MC-WW":
        error(f'branding.APP_NAME 是 {literals.get("APP_NAME")!r}，应为 "MC-WW"。')
    if literals.get("APP_ID") != "mc-ww":
        error(f'branding.APP_ID 是 {literals.get("APP_ID")!r}，应为 "mc-ww"。')

    version = literals.get("APP_VERSION", "")
    if version and not VERSION_RE.match(version):
        error(f"branding.APP_VERSION {version!r} 不是 pyappify 认得的版本格式。")

    # 链接键必须都是 AboutTab 认识的；曾用过 "upstream" 这种不存在的键
    if "LINK_KEYS" in literals:
        unknown = [k for k in literals["LINK_KEYS"] if k not in KNOWN_LINK_KEYS]
        if unknown:
            error(f"branding.LINK_KEYS 含 AboutTab 不识别的键 {unknown}，"
                  f"这些按钮永不显示（合法键：{sorted(KNOWN_LINK_KEYS)}）。")


def check_config_title():
    """config.py 必须真的把标题改成了 MC-WW（不 import，读源码即可）。"""
    source = _read("config.py")
    if not source:
        error("config.py 不见了 —— 打包器靠它读应用配置。")
        return
    if "apply_brand" not in source:
        error("config.py 没有调用 apply_brand —— 打出来的包标题仍是 OK-WW。")

    bridge = _read("src/config.py") or _read("ok/config.py")
    if "OK-WW" in source:
        # config.py 里出现 OK-WW 字样本身不算错（可能只是注释），但要有解释
        if "apply_brand" not in source:
            warn("config.py 里出现 OK-WW 字样，且没有 apply_brand 改写。")


def check_icons():
    for rel in ("icons/icon.png", "icons/icon.ico"):
        if not (ROOT / rel).exists():
            error(f"缺少图标 {rel} —— 打包会失败或显示默认图标。")
    if "icon.png" not in _read("pyappify.yml"):
        error("pyappify.yml 没有指定 icon —— 安装器会用默认图标。")


def check_pipelines(required=True):
    """两个通道各自要有流水线，且都要覆盖 tag 发版。

    CNB 用 ``.cnb.yml``，GitHub 用 ``.github/workflows/``。少一边，那条通道就
    只能推代码、产不出 Release —— 保底通道会名存实亡。
    """
    cnb = ROOT / ".cnb.yml"
    if not cnb.exists():
        message = "缺少 .cnb.yml —— CNB 主通道推 tag 后不会打包发版。"
        if required:
            error(message)
        else:
            warn(message + "（普通 push 不阻断，发版时会拦）")
    else:
        text = _read(".cnb.yml")
        if "tag_push" not in text:
            error(".cnb.yml 没有 tag_push 事件 —— 推 tag 不会触发发版。")
        if "git:release" not in text:
            error(".cnb.yml 的发版流水线没有 git:release —— 产不出 Release。")

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        message = "缺少 .github/workflows/ —— GitHub 保底通道推 tag 后不会打包发版。"
        if required:
            error(message)
        else:
            warn(message + "（普通 push 不阻断，发版时会拦）")
        return

    release_flow = None
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        if "tags:" in text and "gh release create" in text:
            release_flow = path.name
            break
    if release_flow is None:
        error("GitHub workflows 里没有「tag 触发 + gh release create」的发版流水线。")
    else:
        note(f"GitHub 发版流水线：.github/workflows/{release_flow}")


def check_license():
    """AGPL-3.0 衍生作品必须带许可证全文，且同步引擎把它列为受保护路径。"""
    path = ROOT / "LICENSE.txt"
    if not path.exists():
        error("缺少 LICENSE.txt —— AGPL-3.0 要求随分发附带许可证全文。")
        return
    head = _read("LICENSE.txt")[:400]
    if "GNU AFFERO GENERAL PUBLIC LICENSE" not in head:
        error("LICENSE.txt 里没有 AGPL 标题 —— 可能被别的内容覆盖了。")
        return
    if "Version 3" not in head:
        warn("LICENSE.txt 不是 AGPL 第 3 版，与上游许可证不一致。")
    if "LICENSE.txt" not in _read("mcww/sync_engine.py"):
        warn("sync_engine.py 的 PROTECTED_PATHS 没列 LICENSE.txt，"
             "同步上游时可能被覆盖。")


def check_version(tag):
    """tag 名必须是 pyappify 认得的版本格式。"""
    if not tag:
        return
    match = VERSION_RE.match(tag)
    if not match:
        error(f"版本号 {tag!r} 不是 pyappify 认得的格式（v1.2.3 / v1.2.3-beta.1）。"
              "不认的 tag 不会出现在更新列表里，用户永远升不到这个版本。")
        return
    note(f"版本号 {tag} → {'.'.join(match.groups()[:3])}"
         + (f" {match.group(4)}{match.group(5)}" if match.group(5) else ""))


def check_version_consistency(tag):
    """branding 里的版本号要和 tag 对得上，避免"装了却以为没更新"。"""
    if not tag:
        return
    literals = _literal_assignments("mcww/branding.py", {"APP_VERSION"})
    declared = literals.get("APP_VERSION", "")
    if declared and declared.lstrip("v") != tag.lstrip("v"):
        warn(f"branding.APP_VERSION 是 {declared}，tag 是 {tag}。"
             "关于页显示的是 pyappify 探测到的 tag，两者不一致容易让人以为没更新。")


def check_worktree():
    """打 tag 前工作树应该是干净的，否则 tag 内容和源码不一致。"""
    result = subprocess.run(["git", "status", "--porcelain"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        warn("当前目录不是 git 仓库 —— 无法打 tag。先 `git init -b main` 并提交一次。")
        return
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if dirty:
        warn(f"工作树有 {len(dirty)} 个未提交改动。tag 只会记录已提交内容，"
             "未提交的修改不会进安装包 —— 先 commit 再发版。")


def _in_git():
    return (ROOT / ".git").exists()


def check_ignored():
    """绝不能把 backups/ cache/ configs/ 推进仓库。"""
    if not _in_git():
        return
    for rel, why in (("backups", "同步备份，单份约 46MB"),
                     ("cache", "模型缓存，约 21MB"),
                     ("configs", "用户按键与角色代码，属隐私"),
                     ("logs", "运行日志")):
        if not (ROOT / rel).exists():
            continue
        result = subprocess.run(["git", "check-ignore", "-q", rel],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            error(f"{rel}/ 没有被 .gitignore 忽略（{why}）—— 会被提交进仓库。")
    for rel in ("mcww/sync_state.json", "mcww/ui_settings.json"):
        if (ROOT / rel).exists():
            result = subprocess.run(["git", "check-ignore", "-q", rel],
                                    cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                warn(f"{rel} 没有被忽略，会带上本机的同步状态。")


def check_secrets():
    """推送令牌只能在环境变量里，不能落盘进仓库。"""
    patterns = ("MC_WW_CNB_TOKEN", "MC_WW_GITHUB_TOKEN")
    for name in patterns:
        for rel in (f".env.{name.lower()}", f"{name}.txt",
                    f".env.{name.replace('MC_WW_', '').replace('_TOKEN', '').lower()}"):
            if (ROOT / rel).exists():
                error(f"发现疑似令牌文件 {rel} —— 令牌不得入库，"
                      "只放环境变量或本机未跟踪的 .env.local。")


def check_size():
    if not _in_git():
        return
    result = subprocess.run(["git", "ls-files"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return
    files = [f for f in result.stdout.splitlines() if f.strip()]
    if not files:
        note("仓库还没有提交任何文件（tag 会是空的）。")
        return
    note(f"将被 tag 收录的文件：{len(files)} 个")
    big = []
    for rel in files:
        path = ROOT / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 10_000_000:
            big.append((rel, size / 1e6))
    for rel, mb in sorted(big, key=lambda x: -x[1]):
        note(f"大文件 {rel}：{mb:.1f} MB（会显著拖慢首次克隆）")


# ---------------------------------------------------------------- 入口


def run_checks(tag=""):
    """``tag`` 有值 = 发版检查（配置缺失算硬错误）；空 = 普通 push 检查（算警告）。"""
    releasing = bool(tag)
    check_channels(required=releasing)
    check_git_url_stale(required=releasing)
    check_branding_static()
    check_config_title()
    check_icons()
    check_pipelines(required=releasing)
    check_license()
    check_version(tag)
    check_version_consistency(tag)
    check_worktree()
    check_ignored()
    check_secrets()
    check_size()
    return 0 if not errors else 1


def report(as_json=False):
    if as_json:
        print(json.dumps({"ok": not errors, "errors": errors,
                          "warnings": warnings, "notes": notes},
                         ensure_ascii=False, indent=2))
        return 0 if not errors else 1

    for message in errors:
        print(f"✗ {message}")
    for message in warnings:
        print(f"! {message}")
    for message in notes:
        print(f"· {message}")

    if errors:
        print(f"\n✗ {len(errors)} 个错误必须修复后才能发布"
              + (f"（另有 {len(warnings)} 条警告）" if warnings else ""))
        return 1
    if warnings:
        print(f"\n✓ 检查通过，{len(warnings)} 条警告可接受")
    else:
        print("\n✓ 检查全部通过")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="MC-WW 发布前检查（静态，不需要 Qt）")
    parser.add_argument("--tag", default="", help="将要发布的 tag，例如 v1.0.0")
    parser.add_argument("--json", action="store_true", help="机器可读输出（给流水线用）")
    args = parser.parse_args(argv)
    run_checks(args.tag)
    return report(as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
