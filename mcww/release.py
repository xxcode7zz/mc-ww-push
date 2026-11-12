"""MC-WW 发布通道配置层：地址、优先级、可用性探测。

**为什么要有这一层**：MC-WW 有两个「更新」，必须分清，否则很容易互相踩：

1. **上游同步**（:mod:`mcww.sync_engine`）：拉 ok-ww 的**源码**，只替换
   ``src/ ok/ assets/ i18n/`` 等路径。这是「有新角色、新任务」的来源，
   和本节无关。
2. **自有发布**（本模块）：MC-WW 自己的版本，走 git tag + 整包更新。
   这一层决定「从哪个仓库拉自己的新版本」。

发布通道的优先级是 **CNB 优先、GitHub 保底**，理由来自实测而不是偏好：

* 同一份 46MB 代码树，CNB 浅克隆 5.5s，GitHub codeload 只有约 35KB/s；
* 本机实测 GitHub 的 git 协议直接不通（``CONNECT tunnel failed, response 502``），
  而 CNB 正常 —— 国内网络下 GitHub 经常是这种状态；
* 但 GitHub 在海外网络更可靠，所以它保留为**保底**而不是删除。

地址只存一份：``mcww/release.json``。「关于页链接」和「pyappify.yml 的
``git_url``」都从这里派生，避免出现「界面显示我的仓库、更新却去拉别人仓库」。
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
RELEASE_FILE = PACKAGE_DIR / "release.json"
APP_ROOT = PACKAGE_DIR.parent
PYAPPIFY_FILE = APP_ROOT / "pyappify.yml"

# 通道优先级：CNB 在前。这个顺序同时决定两件事 ——
#   1. pyappify.yml 里 China profile 用谁；
#   2. 界面「关于页」默认把「下载」按钮指向谁。
CHANNEL_ORDER = ("cnb", "github")

CHANNEL_LABELS = {"cnb": "CNB", "github": "GitHub"}

# 环境变量名 -> release.json 的键
ENV_KEYS = {
    "github_url": "MC_WW_GITHUB_URL",
    "cnb_url": "MC_WW_CNB_URL",
    "char_code_url": "MC_WW_CHAR_CODE_URL",
    "homepage": "MC_WW_HOMEPAGE",
}

# 一眼就能认出是人手写的占位符片段。这类地址不会报错但必然拉不到东西，
# 所以在打包校验里直接拦掉；真正的"仓库不存在"交给 verify_remote() 探。
PLACEHOLDER_MARKS = (
    "your-name", "yourname", "your_name", "changeme", "change-me",
    "example.com", "example/", "todo", "xxx", "<", ">",
)


def _normalize(url: str) -> str:
    """把用户粘来的地址整理成可用的 git 地址。

    允许直接粘贴网页地址（``https://github.com/me/repo``）、带 ``.git`` 的
    克隆地址，以及末尾多一个斜杠的情况。github / cnb 统一补 ``.git``，
    因为 pyappify 用 dulwich 拉取，带后缀最稳。

    CNB 官方文档说明「是否带 .git 无差异」，但带后缀在 dulwich 与 git CLI
    两条路径上都验证过，所以统一补。
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.endswith("/"):
        url = url[:-1]
    if url.startswith(("http://", "https://")) and not url.endswith(".git"):
        head = url.split("://", 1)[1]
        if head.startswith(("github.com/", "cnb.cool/")):
            url = f"{url}.git"
    return url


def _is_placeholder(url: str) -> bool:
    lowered = (url or "").lower()
    return any(mark in lowered for mark in PLACEHOLDER_MARKS)


def channel_of(url: str) -> str:
    """地址属于哪个通道：``cnb`` / ``github`` / ``""``。"""
    lowered = (url or "").lower()
    if "cnb.cool/" in lowered:
        return "cnb"
    if "github.com/" in lowered:
        return "github"
    return ""


def _read_file() -> dict:
    if not RELEASE_FILE.exists():
        return {}
    try:
        data = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning(f"读取 {RELEASE_FILE.name} 失败: {error!r}")
        return {}
    return data if isinstance(data, dict) else {}


def load() -> dict:
    """返回合并后的配置（环境变量优先），未配置的键为空串。"""
    data = _read_file()
    merged = {}
    for key, env_name in ENV_KEYS.items():
        value = os.environ.get(env_name)
        if value is None:
            value = data.get(key, "")
        merged[key] = _normalize(value if isinstance(value, str) else "")
    merged["configured"] = bool(merged["github_url"] or merged["cnb_url"])
    return merged


def repo_url(prefer: str = "cnb") -> str:
    """取自己的发布仓库地址；没配置返回空串。

    ``prefer="cnb"`` 时国内通道优先（国内网络下 cnb.cool 通常更快），
    没有 cnb 就用 github。两边都空则返回空串，由调用方决定怎么回退。
    """
    data = load()
    order = CHANNEL_ORDER if prefer == "cnb" else tuple(reversed(CHANNEL_ORDER))
    for channel in order:
        value = data.get(f"{channel}_url") or ""
        if value and not _is_placeholder(value):
            return value
    return ""


def configured_channels() -> list:
    """已配置且不是占位符的通道，按优先级排列：``[("cnb", url), ("github", url)]``。"""
    data = load()
    result = []
    for channel in CHANNEL_ORDER:
        url = data.get(f"{channel}_url") or ""
        if url and not _is_placeholder(url):
            result.append((channel, url))
    return result


def download_url(version: str = "") -> str:
    """该版本的下载页地址，没有可用通道时返回空串。

    CNB 的 Release 下载页是 ``https://cnb.cool/<group>/<repo>/-/releases``
    （具体版本再加 ``/tag/<version>``），GitHub 是 ``/releases``。
    这里只是给「关于页」一个可点的入口，不负责真的下载文件。
    """
    channel, url = (configured_channels() or [(None, "")])[0]
    if not url:
        return ""
    base = url[:-4] if url.endswith(".git") else url
    if channel == "cnb":
        return f"{base}/-/releases" + (f"/tag/{version}" if version else "")
    return f"{base}/releases" + (f"/tag/{version}" if version else "")


def _pyappify_urls() -> list:
    """从 pyappify.yml 里取出 (profile 名, git_url)。没有 yml 时返回空列表。"""
    if not PYAPPIFY_FILE.exists():
        return []
    urls = []
    current = ""
    for line in PYAPPIFY_FILE.read_text(encoding="utf-8").splitlines():
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


def expected_bindings(data: dict = None) -> dict:
    """按通道分工算出「两个 profile 各自应该绑定哪个地址」。

    ``China`` 拿 CNB（国内优先），``Global`` 拿 GitHub（海外保底）；
    只配了一个仓库时另一个回退到它，保证两个 profile 都不为空 ——
    否则那半个安装包会去拉一个空地址。
    """
    data = load() if data is None else data
    cnb = data.get("cnb_url") or ""
    github = data.get("github_url") or ""
    return {"China": cnb or github, "Global": github or cnb}


def profile_binding_issues() -> list:
    """pyappify.yml 的 profile 绑定是否偏离了通道分工，返回问题描述列表。"""
    expected = expected_bindings()
    if not any(expected.values()):
        return []  # 还没配置仓库，交给 missing_reason 报「未配置」
    issues = []
    for profile, url in _pyappify_urls():
        want = expected.get(profile)
        if want is None:
            continue
        if url != want:
            issues.append(
                f'profile "{profile}" 绑定的是 {url or "(空)"}，'
                f"按通道分工应为 {want}")
    return issues


def missing_reason() -> str:
    """为什么不能打包，给构建脚本用的中文说明；可以打包时返回空串。

    检查四件事：
    * ``release.json`` 里有没有地址；
    * 地址是不是人手写的占位符；
    * ``pyappify.yml`` 的 ``git_url`` 是否为空（打包器读的是它，不是 json）；
    * profile 绑定是否偏离通道分工（China→CNB、Global→GitHub）。
    """
    data = load()
    problems = []

    if not data["github_url"] and not data["cnb_url"]:
        problems.append("尚未配置 MC-WW 发布仓库地址")
    else:
        bad = [key for key in ("github_url", "cnb_url")
               if data.get(key) and _is_placeholder(data[key])]
        if bad:
            problems.append(f"仓库地址看起来是占位符：{', '.join(bad)}")

    yml = _pyappify_urls()
    if not yml:
        problems.append("找不到 pyappify.yml 的 profile 配置")
    for profile, url in yml:
        if not url:
            problems.append(f'pyappify.yml 中 profile "{profile}" 的 git_url 为空')
        elif "ok-oldking" in url:
            problems.append(
                f'pyappify.yml 中 profile "{profile}" 仍指向上游仓库，'
                "打出来的安装包会变回纯 ok-ww")

    problems.extend(profile_binding_issues())

    if problems:
        return ("；".join(problems) + "。请运行 "
                "`python tools/set_repo.py --cnb <cnb地址> --github <github地址>` "
                "一次写入并同步两处配置，打包器才能生成可用的更新地址。")
    return ""


def verify_remote(url: str, timeout: int = 15) -> dict:
    """检查仓库是否真的存在（尽力而为，私有仓库会误判，只做提示）。

    GitHub 走 API（未登录访问私有仓库会 404，属正常误判）；
    CNB 没有公开匿名 API，走 git 协议的 ``info/refs`` —— 它会返回
    ``smart HTTP`` 的 refs 列表，拿得到就是仓库存在。
    """
    url = _normalize(url)
    if not url:
        return {"ok": False, "reason": "地址为空"}

    import urllib.request

    probe = url
    if probe.endswith(".git"):
        probe = probe[:-4]

    headers = {"User-Agent": "MC-WW-Release-Check/1.0"}
    if "github.com/" in probe:
        probe = probe.replace("https://github.com/", "https://api.github.com/repos/")
        headers["Accept"] = "application/vnd.github+json"
    else:
        # CNB / 其它 git 托管：用 smart-HTTP 的 refs 探测
        probe = f"{probe}.git/info/refs?service=git-upload-pack"

    try:
        request = urllib.request.Request(probe, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", "ignore")
            if not 200 <= getattr(response, "status", 0) < 400:
                return {"ok": False, "reason": f"HTTP {response.status}"}
            # 被镜像/门户页顶掉时会返回 HTML，那不是仓库
            if body.lstrip().lower().startswith(("<!doctype", "<html")):
                return {"ok": False, "reason": "返回 HTML 页面，不是 git 仓库"}
            return {"ok": True, "reason": ""}
    except Exception as error:  # 网络不通也可能是真的仓库，调用方自行决定是否阻断
        return {"ok": False, "reason": str(error)}


def probe_channels(timeout: int = 12) -> dict:
    """按优先级探测已配置通道，返回「第一个可用」的通道。

    这就是「CNB 优先、GitHub 保底」的运行时体现：CNB 不通（或没配）时
    自动落到 GitHub，而不是让用户自己判断该用哪个。
    """
    channels = configured_channels()
    tried = []
    for channel, url in channels:
        result = verify_remote(url, timeout=timeout)
        tried.append({"channel": channel, "url": url,
                      "ok": result["ok"], "reason": result["reason"]})
        if result["ok"]:
            return {"channel": channel, "url": url, "tried": tried, "fallback": len(tried) > 1}
    return {"channel": "", "url": "", "tried": tried, "fallback": False}


def warn_if_unconfigured() -> None:
    """启动时轻提示一次：不影响运行，只是提醒打包前别忘了填。"""
    reason = missing_reason()
    if reason:
        print(f"[MC-WW] {reason}", file=__import__("sys").stderr)
