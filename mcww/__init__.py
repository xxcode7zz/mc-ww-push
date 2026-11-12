"""MC-WW 自有的品牌与同步层。

这个包**不参与上游同步**（见 :mod:`mcww.sync_engine` 的 ``PROTECTED_PATHS``），
所以 MC-WW 的标识、角色代码页、上游同步页都放在这里，上游更新不会把它们冲掉。

对外入口：

* :func:`mcww.branding.apply_brand` —— 把上游 config 改写为 MC-WW 配置；
* :func:`mcww.branding.bootstrap` —— 启动期的运行环境准备（翻译覆盖、更新隔离）；
* :class:`mcww.sync_engine.SyncEngine` —— 检查并同步 ok-ww 上游代码；
* :mod:`mcww.release` —— 发布仓库地址（环境变量 > mcww/release.json）。

这里用懒加载：``mcww.branding`` / ``mcww.sync_engine`` 会连带 import 整个
ok-script 框架（几秒 + 拉起 Qt 相关模块），而 ``tools/set_repo.py`` 这类
维护脚本只想读一个 URL，不该付这个代价。
"""

_LAZY_IMPORTS = {
    "APP_ID": ("mcww.branding", "APP_ID"),
    "APP_NAME": ("mcww.branding", "APP_NAME"),
    "APP_VERSION": ("mcww.branding", "APP_VERSION"),
    "UPSTREAM_REPO_GITHUB": ("mcww.branding", "UPSTREAM_REPO_GITHUB"),
    "apply_brand": ("mcww.branding", "apply_brand"),
    "bootstrap": ("mcww.branding", "bootstrap"),
    "SYNC_SOURCES": ("mcww.sync_engine", "SYNC_SOURCES"),
    "SyncEngine": ("mcww.sync_engine", "SyncEngine"),
    "SyncError": ("mcww.sync_engine", "SyncError"),
    "load_state": ("mcww.sync_engine", "load_state"),
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = target
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value  # 缓存，后续访问不再走 __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_IMPORTS))
