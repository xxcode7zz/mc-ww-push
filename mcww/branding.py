"""MC-WW 品牌层：在不改动上游 ok-ww 的前提下，把应用标识改成 MC-WW。

上游的 ``src/``、``i18n/``、``ok/`` 属于**同步路径**，每次同步会被整体替换，
所以品牌信息不能写进那些文件。本模块做三件事：

1. :func:`apply_brand` 改写上游 config（标题、图标、日志、链接、关于页、页面注册）；
2. :func:`apply_runtime_patches` 在运行时给同步过来的上游模块打补丁，
   把里面的 ``ok-ww`` 残留文案换成 MC-WW；
3. :func:`install_translation_fallback` 给 gettext 目录挂载 MC-WW 自有的
   ``mcww/i18n`` 词条，让新增页面的中文文案能翻译，而不必改动上游 ``.po``。

这些都不在同步路径里，上游更新不会把它们冲掉。
"""

import sys
from pathlib import Path

from ok import Logger

from mcww import release

logger = Logger.get_logger(__name__)

# ---------------------------------------------------------------- 应用标识

APP_NAME = "MC-WW"
APP_ID = "mc-ww"
APP_VERSION = "v1.0.0"

# 上游基线（同步引擎以这些仓库为源）
UPSTREAM_NAME = "ok-ww"
UPSTREAM_REPO_GITHUB = "https://github.com/ok-oldking/ok-wuthering-waves"
UPSTREAM_REPO_UPDATE_GITHUB = "https://github.com/ok-oldking/ok-ww-update"
UPSTREAM_REPO_UPDATE_CNB = "https://cnb.cool/ok-oldking/ok-ww-update2.git"

# MC-WW 自己的仓库地址：唯一来源是 mcww/release.json（由 tools/set_repo.py 写入）。
# 没配置时**退回上游地址** —— 宁可链接指向 ok-ww 说明页，也不要把用户
# 送到一个不存在的仓库（曾经写死过 github.com/ok-oldking/mc-ww-update，
# 实测 404，那是纯占位地址）。
#
# 地址按**用途**取，不是笼统取一个：
#   * 「GitHub」按钮要真的去 GitHub，所以取 repo_url("github")；
#   * 「Download」按钮要国内能打开，所以取 download_url()（CNB 优先）。
# 两个都没配就退到上游说明页，别把用户送到不存在的仓库。
MC_WW_GITHUB_URL = release.repo_url("github") or UPSTREAM_REPO_GITHUB
MC_WW_DOWNLOAD_URL = release.download_url()
MC_WW_CHAR_CODE_URL = release.load()["char_code_url"] or MC_WW_GITHUB_URL
MC_WW_HOMEPAGE = release.load()["homepage"] or "https://ok-script.com/ok-ww"

ICON_PATH = "icons/icon.png"
ICON_ICO_PATH = "icons/icon.ico"

# 关于页按钮的键名。**必须**落在 ok/ui/qt/about/AboutTab.py 的 ``LINKS`` 里，
# 否则按钮永远不会被创建（曾被塞进 "upstream" 键，那张按钮从来没出现过）。
# tools/check_release.py 会拿这个常量与 AboutTab.LINKS 做交叉校验。
LINK_KEYS = ("github", "download")

PACKAGE_DIR = Path(__file__).resolve().parent
APP_ROOT = PACKAGE_DIR.parent

# ---------------------------------------------------------------- 品牌文案

ABOUT_HTML = """
    <p style="color:red;">
    <strong>本软件是免费开源的。</strong> 如果你被收费，请立即退款。
    </p>
    <p style="color:red;">
        <strong>本软件仅供个人使用，用于学习Python编程、计算机视觉、UI自动化等。</strong> 请勿将其用于任何营利性或商业用途。
    </p>
    <p style="color:red;">
        <strong>使用本软件可能会导致账号被封。</strong> 请在了解风险后再使用。
    </p>
    <p style="color:#666;">
    MC-WW 基于 <a href="https://ok-script.com">ok-script</a> 框架与
    <a href="https://github.com/ok-oldking/ok-wuthering-waves">ok-ww</a> 开源项目构建，
    遵循上游 AGPL-3.0 许可证；本程序的角色战斗代码、识别模板等均来自上游同步。
    上游代码版权归 ok-ww 作者所有。
    </p>
"""

# 上游报错里带着 ok-ww 字样，MC-WW 改成自己的名字
SKILL_FAILED_TEMPLATE = "Click skill failed, check if the keybinding is correct in {app} settings!"


# ---------------------------------------------------------------- config 改写

_VERSION_LINE_RE = None


def _packaged_version():
    """从仓库根 ``config.py`` 读出版本号字面值，读不到就返回空串。

    为什么不直接 ``from config import version``：``config.py`` 正是本函数的
    调用方（它 import 了 apply_brand），直接 import 会形成循环。这里改成
    读源码文本 —— 只认 ``version = "..."`` 这一种形状，与打包脚本
    ``ok.update.inline_ok_requirements`` 改写的那行完全对应。

    这样打包产物里 config.py 被写成 tag 值、而 branding.py 里的
    APP_VERSION 还是源码默认值时，运行时仍能显示正确版本号。
    """
    global _VERSION_LINE_RE
    import re

    if _VERSION_LINE_RE is None:
        _VERSION_LINE_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
    try:
        source = (APP_ROOT / "config.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _VERSION_LINE_RE.search(source)
    return match.group(1) if match else ""


def apply_brand(upstream_config: dict) -> dict:
    """把上游 config 就地改成 MC-WW 的配置并返回它。"""

    config = upstream_config

    # --- 窗口标题与图标 ---
    config["gui_title"] = APP_NAME
    config["gui_icon"] = ICON_PATH
    config["app_name"] = APP_NAME
    config["app_id"] = APP_ID

    # --- 版本号 ---
    # 上游把 version 写在 upstream_config.py 的模块级变量里，config["version"]
    # 直接引用它 —— 所以不覆盖的话，关于页与更新检查显示的会是上游版本
    # （v3.8.0），用户会以为自己装的是 ok-ww。
    #
    # 取值的优先级：config.py 里的 ``version``（打包时被 inline_ok_requirements
    # 改写成 tag 值）> APP_VERSION（源码里的默认值）。
    # 两者平时相等；只有打包产物里 config.py 被改过而本文件没被改，
    # 所以运行时必须以 config.py 为准，否则安装包里显示的仍是旧版本号。
    config["version"] = _packaged_version() or APP_VERSION

    # --- 日志改名，避免与 ok-ww 同时运行抢同一个文件 ---
    config["log_file"] = f"logs/{APP_ID}.log"
    config["error_log_file"] = f"logs/{APP_ID}_error.log"

    # --- 配置目录：角色自定义代码存在 configs/ 下，两端独立 ---
    config["config_folder"] = "configs"

    # --- 关于页 ---
    config["about"] = ABOUT_HTML

    # --- 链接：指向 MC-WW，保留上游 FAQ 文档 ---
    # 键名必须落在 ok/ui/qt/about/AboutTab.py 的 LINKS 里，否则永不渲染。
    # 曾经这里塞过 "upstream" 键 —— LINKS 里没有它，那张按钮从来没出现过；
    # 同时 "download" 从未赋值，于是关于页一直没有下载入口。
    upstream_links = config.get("links") or {}
    brand_links = {"github": MC_WW_GITHUB_URL}
    if MC_WW_DOWNLOAD_URL:
        brand_links["download"] = MC_WW_DOWNLOAD_URL
    if not upstream_links:
        upstream_links = {"default": dict(brand_links)}
    else:
        for locale_key, links in list(upstream_links.items()):
            merged = dict(links)
            merged.update(brand_links)
            upstream_links[locale_key] = merged
    config["links"] = upstream_links

    # --- 关掉上游 pyappify 强制整体升级，否则 MC-WW 会被上游安装包覆盖 ---
    config.pop("update_pyappify", None)

    # --- 注册 MC-WW 自有页面 ---
    # 页面放在受保护的 mcww/ 包里：src/ 是同步路径，下次同步会被上游整体替换，
    # 注册到那里的页面会在第一次同步后就消失（ModuleNotFoundError）。
    custom_tabs = [list(tab) for tab in (config.get("custom_tabs") or [])]
    existing = {tuple(spec) for spec in custom_tabs}
    for spec in CUSTOM_TABS:
        if tuple(spec) not in existing:
            custom_tabs.append(list(spec))
    config["custom_tabs"] = custom_tabs

    return config


# MC-WW 自有页面（模块路径, 类名）。由 MainWindow 用 init_class_by_name 实例化，
# 所以模块必须可 import —— 放在受保护的 mcww 包里才安全。
CUSTOM_TABS = (
    ("mcww.ui_char_code_tab", "McWwCharacterCodeTab"),
    ("mcww.ui_sync_tab", "McWwSyncTab"),
)


# ---------------------------------------------------------------- 运行时补丁


def _patch_skill_failed_message():
    """上游 ``BaseChar.alert_skill_failed`` 里写死了 ok-ww 字样，改成 MC-WW。"""
    try:
        from src.char.BaseChar import BaseChar
    except Exception as error:  # 上游改了模块名，补丁失效但不该阻断启动
        _warn(f"跳过技能报错文案补丁: {error}")
        return

    original = getattr(BaseChar, "alert_skill_failed", None)
    if original is None or getattr(original, "_mcww_patched", False):
        return

    def alert_skill_failed(self):
        message = SKILL_FAILED_TEMPLATE.format(app=APP_NAME)
        self.task.log_error(self.task.tr(message), notify=True)
        self.task.screenshot("click_resonance too long, breaking")

    alert_skill_failed._mcww_patched = True
    alert_skill_failed.__wrapped__ = original
    BaseChar.alert_skill_failed = alert_skill_failed


def _patch_character_code_links():
    """角色代码页和角色代码任务里的 ok-ww 链接，指向 MC-WW / 上游说明页。"""
    try:
        import src.gui.CharacterCodeTab as tab_module
    except Exception as error:
        _warn(f"跳过角色代码页链接补丁: {error}")
        tab_module = None
    if tab_module is not None and hasattr(tab_module, "UPLOAD_TEAM_URL"):
        tab_module.UPLOAD_TEAM_URL = MC_WW_CHAR_CODE_URL

    # 上游的 CharacterCodeTask 依赖 WebCustomTab，而当前框架没有这个符号，
    # 该任务本来就无法使用（MC-WW 的角色代码功能走 Qt 版页面）。这里不算失败，
    # 否则每次启动都会往 stderr 打一条误导性的警告。
    if _has_web_tab_support():
        try:
            import src.task.CharacterCodeTask  # noqa: F401
        except Exception as error:
            _warn(f"跳过角色代码任务链接补丁: {error}")


def _has_web_tab_support():
    try:
        import ok
    except Exception:
        return False
    return hasattr(ok, "WebCustomTab")


def _patch_about_projects():
    """在"其他项目"里补一张 MC-WW 卡片，说明它与 ok-ww 的关系。

    幂等标记不能打到被 `@staticmethod` 包裹后的对象上：类的 `_other_projects`
    取到的是底层函数，标记留在 staticmethod 外壳里，重复调用会看不到标记、
    于是每次启动都往列表里塞一张重复卡片。
    """
    if _state.get("about_patched"):
        return
    try:
        from ok.ui.qt.about.AboutTab import AboutTab
    except Exception as error:
        _warn(f"跳过关于页补丁: {error}")
        return

    original = getattr(AboutTab, "_other_projects", None)
    if original is None:
        return

    import functools

    @functools.wraps(original)
    def _other_projects(config):
        projects = original(config)
        projects.insert(0, {
            "name": f"{APP_NAME} (Upstream)",
            "url": UPSTREAM_REPO_GITHUB,
            "website": MC_WW_HOMEPAGE,
        })
        return projects

    AboutTab._other_projects = staticmethod(_other_projects)
    _state["about_patched"] = True


def _patch_pyappify_self_update():
    """关掉上游「应用更新」的整包自更新。

    这是个**破坏性**风险，不关不行：上游 AboutTab 的 UpdateCard 会调用
    ``pyappify.get_version_list`` / ``update_to_version``，从 ok-ww 的发布
    仓库下载整个应用包并原地安装。装完以后 ``config.py``、``mcww/``、图标、
    ``pyappify.yml`` 全被 ok-ww 的版本覆盖 —— MC-WW 直接变回 ok-ww。

    MC-WW 的更新通道是「上游同步」页（只替换源码路径、受保护路径有 MD5 校验
    与回滚），所以这里把 pyappify 的自更新入口摘掉，让关于页不再显示那张
    能把程序改回 ok-ww 的卡片。用户仍可通过 Upstream Sync 页更新。

    只影响运行中的进程，不改 ``pyappify/`` 文件本身（那是同步路径）。
    """
    if _state.get("self_update_patched"):
        return
    try:
        import pyappify
    except Exception as error:
        _warn(f"跳过自更新补丁: {error}")
        return

    for name in ("get_version_list", "update_to_version"):
        if hasattr(pyappify, name):
            try:
                delattr(pyappify, name)
            except (AttributeError, TypeError) as error:
                _warn(f"移除 pyappify.{name} 失败: {error}")
    _state["self_update_patched"] = True


# 补丁的幂等状态。用模块级字典而不是往函数/staticmethod 上挂属性，
# 避免上面说的「标记挂错对象」问题。
_state = {}


_PATCHES = (
    _patch_skill_failed_message,
    _patch_character_code_links,
    _patch_about_projects,
    _patch_pyappify_self_update,
)


def apply_runtime_patches():
    """给同步过来的上游模块打品牌补丁。幂等，可重复调用。"""
    for patch in _PATCHES:
        try:
            patch()
        except Exception as error:
            _warn(f"品牌补丁 {patch.__name__} 失败: {error}")


# ---------------------------------------------------------------- 翻译回退


def _locale_candidates(locale_name):
    """把 ``zh_CN`` 展开成 gettext 需要的候选语言列表。"""
    if not locale_name:
        return []
    language = str(locale_name).replace("-", "_")
    candidates = [language]
    if "_" in language:
        candidates.append(language.split("_")[0])
    candidates.append("en")
    return candidates


def _install_translation_fallback():
    """给 ``ok.core.translation.get_translations`` 挂上 ``mcww/i18n`` 词条。"""
    from ok.core import translation as ok_translation

    current = getattr(ok_translation, "get_translations", None)
    if current is None or getattr(current, "_mcww_patched", False):
        return

    import gettext

    def get_translations(language):
        # 上游只带了 es_ES / ja_JP / ko_KR / zh_CN / zh_TW 五种 .mo，
        # 系统语言是 en_US 时 gettext 会抛 FileNotFoundError。上游用裸 except
        # 吞掉了它，结果是「翻译安装失败 → 所有 tr() 原样返回」。MC-WW 在这里
        # 兜住异常，至少保证自己的词条目录仍然可用。
        try:
            base = current(language)
        except Exception as error:
            logger.debug(f"上游词条不可用（{language}）：{error}")
            base = None
        try:
            extra = gettext.translation(
                "mcww", str(PACKAGE_DIR / "i18n"),
                languages=_locale_candidates(language), fallback=True,
            )
        except Exception as error:
            _warn(f"加载 MC-WW 翻译失败: {error}")
            return base
        if base is None:
            return extra
        # base 命中上游词条优先，未收录的 MC-WW 文案回退到 mcww 目录
        base.add_fallback(extra)
        return base

    get_translations._mcww_patched = True
    ok_translation.get_translations = get_translations


# ---------------------------------------------------------------- 启动引导


def bootstrap(app_dir=None):
    """启动期准备：品牌补丁 + 翻译回退 + 目录与更新隔离。"""
    _ensure_custom_code_dirs()
    apply_runtime_patches()
    try:
        _install_translation_fallback()
    except Exception as error:
        _warn(f"翻译回退安装失败: {error}")
    # 发布仓库没配置只提示、不阻断：本地跑源码完全不需要它，
    # 但打包前必须填好，所以提前一句提醒比事后排查省事。
    try:
        release.warn_if_unconfigured()
    except Exception as error:
        _warn(f"检查发布仓库配置失败: {error}")
    return app_dir or APP_ROOT


def _ensure_custom_code_dirs():
    """角色代码目录提前建好，用户点开页面就能看到自己的团队。"""
    try:
        from ok.util.config import Config
        root = Path(Config.config_folder)
    except Exception:
        root = APP_ROOT / "configs"
    for folder in ("custom_chars", "custom_teams"):
        try:
            (root / folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def _warn(message):
    print(f"[MC-WW] {message}", file=sys.stderr)
