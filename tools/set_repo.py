"""把 MC-WW 的双通道发布地址写到唯一的地方，并同步生成 pyappify.yml。

为什么要有这个脚本：仓库地址被两个地方消费 ——

* ``pyappify.yml`` 的 ``git_url``：打包器用它生成安装包的更新源；
* ``mcww/release.json``：程序里「关于页 / 角色代码页 / 同步页」的链接。

手改两处必然会出现"界面里是我仓库、更新却去拉别人仓库"这种错配，
所以这里统一入口：一次写入，两处一致。

通道分工（CNB 国内优先、GitHub 保底）：

===========  =========================  =============================
profile      绑定的 git_url              给谁用
===========  =========================  =============================
``China``    ``cnb_url``（缺则 github）   国内网络，走 cnb.cool
``Global``   ``github_url``（缺则 cnb）   海外网络，走 github.com
===========  =========================  =============================

用法（在 MC-WW 目录下执行）：

    python tools/set_repo.py --cnb https://cnb.cool/你的路径/mc-ww
    python tools/set_repo.py --github https://github.com/你的用户名/mc-ww
    python tools/set_repo.py --cnb <cnb地址> --github <github地址>   # 一次写两个
    python tools/set_repo.py --check          # 校验两处是否一致、profile 绑定是否正确
    python tools/set_repo.py --check --strict # 连通性也不通就返回非 0（给 CI 用）
    python tools/set_repo.py --clear          # 清空，回到"还没建仓库"状态

地址可以直接粘网页地址，脚本会补 ``.git``（dulwich 与 git CLI 两条路径都验证过）。
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_FILE = ROOT / "mcww" / "release.json"
PYAPPIFY_FILE = ROOT / "pyappify.yml"

# 未配置自己主页时的兜底地址（上游说明页），保证 website 字段不空
UPSTREAM_HOMEPAGE = "https://ok-script.com/ok-ww"

sys.path.insert(0, str(ROOT))


def _normalize(url: str) -> str:
    from mcww.release import _normalize as normalize

    return normalize(url)


def _classify(url: str) -> str:
    """根据地址判断它属于哪个平台，返回 release.json 的键名。"""
    lowered = url.lower()
    if "cnb.cool/" in lowered:
        return "cnb_url"
    if "github.com/" in lowered:
        return "github_url"
    raise SystemExit(f"只认得 github.com / cnb.cool 的地址，收到：{url}")


def _load_release() -> dict:
    if RELEASE_FILE.exists():
        try:
            data = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {"github_url": "", "cnb_url": "", "char_code_url": "", "homepage": ""}


def _save_release(data: dict) -> None:
    # 保留说明字段，方便后来人知道这文件不该手改
    payload = {
        "_readme": [
            "MC-WW 发布仓库地址的唯一配置源。",
            "不要手改这里 —— 运行 `python tools/set_repo.py --cnb <地址> --github <地址>`",
            "会自动写入本文件，并同步改写 pyappify.yml 里两个 profile 的 git_url。",
            "通道分工：China profile 走 cnb_url（国内优先），Global profile 走 github_url（海外保底）。",
            "留空表示「还没建仓库」：程序照常本地运行，但打包前必须填好，否则安装包会去拉一个不存在的仓库。",
        ],
        "github_url": data.get("github_url", ""),
        "cnb_url": data.get("cnb_url", ""),
        "char_code_url": data.get("char_code_url", ""),
        "homepage": data.get("homepage", ""),
    }
    RELEASE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def _patch_pyappify(github_url: str, cnb_url: str, allow_empty: bool = False) -> int:
    """把两个 profile 的 git_url 改写为配置值，返回实际替换处数。

    不整份重写 yml（会丢注释与未知字段），只做定向替换，并且校验确实改到了
    两处 —— 少改一处就会留下旧地址，打包时静默用错仓库。
    """
    text = PYAPPIFY_FILE.read_text(encoding="utf-8")
    original = text
    replacements = 0

    def replace_profile(block_name: str, url: str) -> None:
        nonlocal text, replacements
        if not url and not allow_empty:
            return
        # 匹配 `- name: "xxx"` 之后紧随的 git_url 行
        pattern = re.compile(
            r'(- name:\s*"' + re.escape(block_name) + r'"\s*\n\s*git_url:\s*")[^"]*(")')

        def repl(match):
            nonlocal replacements
            replacements += 1
            return match.group(1) + url + match.group(2)

        text = pattern.sub(repl, text)

    # 国内 profile 优先拿 CNB；Global 优先拿 GitHub。任一为空就退到另一个，
    # 只有一个仓库的用户也能打包（只是失去"国内/海外分流"的收益）。
    replace_profile("China", cnb_url or github_url)
    replace_profile("Global", github_url or cnb_url)

    if text != original:
        PYAPPIFY_FILE.write_text(text, encoding="utf-8")
    if not allow_empty and replacements != 2:
        print(f"! 警告：pyappify.yml 只匹配到 {replacements}/2 处 git_url，"
              "请检查文件格式是否被改过。", file=sys.stderr)
    return replacements


def _patch_homepage(homepage: str) -> None:
    """把 pyappify.yml 的 ``website`` 指到项目主页（留空则保持原样）。"""
    if not homepage:
        return
    _set_website(homepage)


def _set_website(homepage: str) -> None:
    text = PYAPPIFY_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r'(^\s*website:\s*")[^"]*(")', re.MULTILINE)
    patched, count = pattern.subn(lambda m: m.group(1) + homepage + m.group(2), text, count=1)
    if count and patched != text:
        PYAPPIFY_FILE.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------- 校验


def _expected_bindings(data: dict) -> dict:
    """按通道分工算出「两个 profile 各自应该是什么地址」。"""
    from mcww.release import expected_bindings

    return expected_bindings(data)


def _check(strict: bool = False) -> int:
    from mcww.release import _pyappify_urls, load, missing_reason, probe_channels

    data = load()
    reason = missing_reason()
    print("mcww/release.json:")
    print(f"  CNB（国内优先） : {data['cnb_url'] or '(未设)'}")
    print(f"  GitHub（保底）  : {data['github_url'] or '(未设)'}")

    yml = dict(_pyappify_urls())
    expected = _expected_bindings(data)
    print("pyappify.yml 当前 git_url：")
    mismatched = []
    for profile in ("China", "Global"):
        url = yml.get(profile, "")
        want = expected.get(profile, "")
        if not url:
            flag = "-"
        elif want and url != want:
            flag = "!"
            mismatched.append(profile)
        elif want:
            flag = "✓"
        else:
            flag = "?"
        print(f"  [{profile}] {url or '(空)'}  {flag}")

    if reason:
        print(f"\n✗ 不能打包：{reason}")
        return 1

    if mismatched:
        print(f"\n✗ profile 绑定与通道分工不一致：{mismatched}。"
              "请重新运行 `python tools/set_repo.py --cnb <地址> --github <地址>`。")
        return 1

    if "ok-oldking" in " ".join(yml.values()):
        print("\n✗ 仍有 profile 指向上游 ok-ww 仓库，打出来的包会变回纯 ok-ww。")
        return 1

    # 连通性：CNB 优先、GitHub 保底，运行时会自动降级
    probe = probe_channels()
    for item in probe["tried"]:
        label = "CNB" if item["channel"] == "cnb" else "GitHub"
        if item["ok"]:
            print(f"✓ {label} 仓库可达：{item['url']}")
        else:
            print(f"! {label} 仓库无法匿名访问：{item['url']} —— {item['reason']}"
                  "（私有仓库属正常，流水线内用令牌访问）")

    if probe["channel"]:
        note = "（已从 CNB 降级到 GitHub）" if probe["fallback"] else ""
        print(f"\n✓ 当前可用通道：{probe['channel'].upper()}{note}")
        return 0

    print("\n! 所有已配置通道都没探通。若仓库是私有的，这是正常现象；"
          "否则请检查网络或地址。")
    if strict:
        print("✗ --strict：没有任何通道可达，判失败。")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="设置 MC-WW 双通道发布地址（同步 mcww/release.json 与 pyappify.yml）")
    parser.add_argument("urls", nargs="*",
                        help="（兼容旧用法）直接给 1~2 个仓库地址，按平台自动归类")
    parser.add_argument("--cnb", default="", metavar="URL", help="CNB 仓库地址（国内优先通道）")
    parser.add_argument("--github", default="", metavar="URL", help="GitHub 仓库地址（保底通道）")
    parser.add_argument("--check", action="store_true", help="只校验，不修改")
    parser.add_argument("--strict", action="store_true",
                        help="配合 --check：连通性全不通时返回非 0（给 CI 用）")
    parser.add_argument("--clear", action="store_true", help="清空配置")
    parser.add_argument("--char-code-url", default="", help="角色代码提交页地址（可选）")
    parser.add_argument("--homepage", default="", help="项目主页地址（可选）")
    args = parser.parse_args(argv)

    if args.check:
        return _check(strict=args.strict)

    if args.clear:
        _save_release({})
        _patch_pyappify("", "", allow_empty=True)
        _set_website(UPSTREAM_HOMEPAGE)
        print("已清空仓库配置（程序仍可本地运行，但打包前需重新设置）。")
        return 0

    if not (args.urls or args.cnb or args.github):
        parser.print_help()
        print("\n提示：仓库还没建？先去 CNB（推荐，国内快）或 GitHub 建一个空仓库，"
              "再把地址填进来。")
        return 2

    data = _load_release()
    for raw in args.urls:
        url = _normalize(raw)
        data[_classify(url)] = url
    if args.cnb:
        data["cnb_url"] = _normalize(args.cnb)
    if args.github:
        data["github_url"] = _normalize(args.github)
    if args.char_code_url:
        data["char_code_url"] = _normalize(args.char_code_url)
    if args.homepage:
        data["homepage"] = args.homepage.strip()

    _save_release(data)
    _patch_homepage(data.get("homepage", ""))
    expected = _expected_bindings(data)
    replaced = _patch_pyappify(data.get("github_url", ""), data.get("cnb_url", ""))

    print("已写入配置：")
    print(f"  mcww/release.json : CNB={data.get('cnb_url') or '-'}  "
          f"GitHub={data.get('github_url') or '-'}")
    print(f"  pyappify.yml      : China → {expected['China'] or '(空)'}")
    print(f"                      Global → {expected['Global'] or '(空)'}"
          f"（替换 {replaced}/2 处）")
    print("\n接下来：")
    print("  python tools/set_repo.py --check   # 确认绑定正确、仓库可达")
    print("  python tools/publish.py --dry-run  # 演练一次打 tag")
    print("  真正发布：python tools/publish.py v1.0.0（需要访问令牌，见 README）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
