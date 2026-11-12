"""MC-WW 自有界面的翻译词条构建脚本。

为什么需要它：上游 ``i18n/`` 属于同步路径，每次同步都会被整体替换，所以
MC-WW 新页面的中文不能写进上游的 ``ok.po``。这里的词条独立放在
``mcww/i18n/``（受保护路径），运行时由
:func:`mcww.branding._install_translation_fallback` 作为 gettext 回退层挂上去。

用法（在项目根目录）::

    .venv/Scripts/python.exe -m mcww.i18n_build

脚本会扫描 ``mcww/ui_*.py`` 里的 ``tr("...")`` 字面量：

* 已存在的词条保留原译文；
* 新出现的词条以空译文加入，提示补翻译；
* 源码里已删除的词条一并清掉，避免 po 越滚越脏。

``.mo`` 由 po 编译而来，程序运行时只读 ``.mo``。
"""

import ast
import re
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
I18N_DIR = PACKAGE_DIR / "i18n"
LOCALES = ("zh_CN", "zh_TW")

# 需要扫描的源文件（MC-WW 自有页面）
SOURCE_GLOB = "ui_*.py"

PO_HEADER = {
    "Project-Id-Version": "MC-WW",
    "Language": "{locale}",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "8bit",
}

# 新词条的初始译文。已有 po 条目以 po 里的人工译文为准，这里只负责「第一次
# 生成时就带上中文」，免得每次加一句文案都要手动翻一遍。译文最终仍落在 po 里，
# 想改措辞直接改 po 即可（重跑本脚本不会覆盖已有 msgstr）。
TRANSLATIONS = {
    "zh_CN": {
        "Character Code": "角色代码",
        "Open Upstream Sync": "打开上游同步",
        "Please open the Upstream Sync page manually.": "请手动打开「上游同步」页面。",
        "Try syncing upstream first. If it still fails, open an issue with the log "
        "attached.": "请先尝试同步上游代码；如仍失败，请附上日志提交问题。",
        "The character code editor from {app}'s upstream is missing, most likely "
        "because upstream renamed or moved it.":
            "未找到 {app} 上游的角色代码编辑器，可能是上游改名或移动了该模块。",
        "Upstream Sync": "上游同步",
        "Check for Updates": "检查更新",
        "Sync Now": "立即同步",
        "Version Status": "版本状态",
        "Sync Settings": "同步设置",
        "Upstream Sources": "上游来源",
        "Syncing upstream code, please wait…": "正在同步上游代码，请稍候…",
        "Download → replace → verify. The window may freeze briefly.":
            "下载 → 替换 → 校验。期间窗口可能短暂卡顿。",
        "Check upstream on startup": "启动时检查上游",
        "Checks the upstream version quietly after startup and shows a hint when a "
        "newer version exists. It never changes code on its own.":
            "启动后在后台静默检查上游版本，发现新版本时给出提示；不会自行改动代码。",
        "Syncing replaces upstream code only (src / ok / assets / i18n and so on). "
        "MC-WW branding and its own pages are never overwritten, and a failed check "
        "rolls everything back.":
            "同步只替换上游代码（src / ok / assets / i18n 等），MC-WW 的品牌配置与自有页面"
            "不会被覆盖；校验失败会自动回滚。",
        "Not synced yet — currently running on the bundled baseline.":
            "尚未同步过，当前运行的是内置基线版本。",
        "Click \"Sync Now\" to pull the latest ok-ww code.":
            "点击「立即同步」拉取最新的 ok-ww 代码。",
        "Click \"Sync Now\" to update to it.": "点击「立即同步」升级到该版本。",
        "Check finished": "检查完成",
        "Sync failed": "同步失败",
        "Local upstream version: {version}": "本地上游版本：{version}",
        "Synced to upstream {version}": "已同步至上游 {version}",
        "Updated paths: {paths}. Restart {app} to apply.":
            "已更新：{paths}。请重启 {app} 生效。",
        "Sync finished — restart {app} to apply": "同步完成，请重启 {app} 生效",
        "Quit Now": "立即退出",
        "Last sync: {time}": "上次同步：{time}",
        "Source: {source}": "来源：{source}",
        "New upstream version found: {version} (local {local})":
            "发现上游新版本：{version}（本地 {local}）",
        "Already up to date: {version}": "已是最新版本：{version}",
        "Sync failed: {error}": "同步失败：{error}",
        "none": "无",
        "Check failed: {error}": "检查失败：{error}",
        "Release Repository": "发布仓库",
        "No release repository configured yet — the app runs locally, "
        "but packaging needs one. Run: python tools/set_repo.py <your repo>":
            "尚未配置发布仓库地址 —— 程序可以本地运行，但打包前必须设置。"
            "请执行：python tools/set_repo.py <你的仓库地址>",
        "No release repository configured yet — the app runs locally, "
        "but packaging needs one. Run: "
        "python tools/set_repo.py --cnb <url> --github <url>":
            "尚未配置发布仓库地址 —— 程序可以本地运行，但打包前必须设置。"
            "请执行：python tools/set_repo.py --cnb <CNB地址> --github <GitHub地址>",
        "primary": "优先",
        "fallback": "保底",
        "Releases": "发布页",
        "Only one channel is configured. Add the other one as a mirror: "
        "python tools/set_repo.py --cnb <url> --github <url>":
            "只配置了一个通道。建议再补一个做镜像："
            "python tools/set_repo.py --cnb <CNB地址> --github <GitHub地址>",
    },
    "zh_TW": {
        "Character Code": "角色代碼",
        "Open Upstream Sync": "開啟上游同步",
        "Please open the Upstream Sync page manually.": "請手動開啟「上游同步」頁面。",
        "Try syncing upstream first. If it still fails, open an issue with the log "
        "attached.": "請先嘗試同步上游程式碼；如仍失敗，請附上日誌提交問題。",
        "The character code editor from {app}'s upstream is missing, most likely "
        "because upstream renamed or moved it.":
            "未找到 {app} 上游的角色代碼編輯器，可能是上游改名或移動了該模組。",
        "Upstream Sync": "上游同步",
        "Check for Updates": "檢查更新",
        "Sync Now": "立即同步",
        "Version Status": "版本狀態",
        "Sync Settings": "同步設定",
        "Upstream Sources": "上游來源",
        "Syncing upstream code, please wait…": "正在同步上游程式碼，請稍候…",
        "Download → replace → verify. The window may freeze briefly.":
            "下載 → 取代 → 校驗。期間視窗可能短暫卡頓。",
        "Check upstream on startup": "啟動時檢查上游",
        "Checks the upstream version quietly after startup and shows a hint when a "
        "newer version exists. It never changes code on its own.":
            "啟動後在背景靜默檢查上游版本，發現新版本時給出提示；不會自行變更程式碼。",
        "Syncing replaces upstream code only (src / ok / assets / i18n and so on). "
        "MC-WW branding and its own pages are never overwritten, and a failed check "
        "rolls everything back.":
            "同步只取代上游程式碼（src / ok / assets / i18n 等），MC-WW 的品牌設定與自有頁面"
            "不會被覆寫；校驗失敗會自動回滾。",
        "Not synced yet — currently running on the bundled baseline.":
            "尚未同步過，目前執行的是內建基線版本。",
        "Click \"Sync Now\" to pull the latest ok-ww code.":
            "點擊「立即同步」取得最新的 ok-ww 程式碼。",
        "Click \"Sync Now\" to update to it.": "點擊「立即同步」升級至該版本。",
        "Check finished": "檢查完成",
        "Sync failed": "同步失敗",
        "Local upstream version: {version}": "本地上游版本：{version}",
        "Synced to upstream {version}": "已同步至上游 {version}",
        "Updated paths: {paths}. Restart {app} to apply.":
            "已更新：{paths}。請重新啟動 {app} 生效。",
        "Sync finished — restart {app} to apply": "同步完成，請重新啟動 {app} 生效",
        "Quit Now": "立即結束",
        "Last sync: {time}": "上次同步：{time}",
        "Source: {source}": "來源：{source}",
        "New upstream version found: {version} (local {local})":
            "發現上游新版本：{version}（本地 {local}）",
        "Already up to date: {version}": "已是最新版本：{version}",
        "Sync failed: {error}": "同步失敗：{error}",
        "none": "無",
        "Check failed: {error}": "檢查失敗：{error}",
        "Release Repository": "發布倉庫",
        "No release repository configured yet — the app runs locally, "
        "but packaging needs one. Run: python tools/set_repo.py <your repo>":
            "尚未設定發布倉庫位址 —— 程式可本機執行，但封裝前必須設定。"
            "請執行：python tools/set_repo.py <你的倉庫位址>",
        "No release repository configured yet — the app runs locally, "
        "but packaging needs one. Run: "
        "python tools/set_repo.py --cnb <url> --github <url>":
            "尚未設定發布倉庫位址 —— 程式可本機執行，但封裝前必須設定。"
            "請執行：python tools/set_repo.py --cnb <CNB位址> --github <GitHub位址>",
        "primary": "優先",
        "fallback": "保底",
        "Releases": "發布頁",
        "Only one channel is configured. Add the other one as a mirror: "
        "python tools/set_repo.py --cnb <url> --github <url>":
            "只設定了一個通道。建議再補一個作為鏡像："
            "python tools/set_repo.py --cnb <CNB位址> --github <GitHub位址>",
    },
}


def collect_msgids() -> list:
    """抓 ``tr("...")`` 调用里的字符串字面量，按出现顺序去重。"""
    found = []
    for path in sorted(PACKAGE_DIR.glob(SOURCE_GLOB)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name != "tr" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                text = first.value
                if text and text not in found:
                    found.append(text)
    return found


def build_locale(locale: str, msgids: list) -> tuple:
    """把 msgids 合并进该语言的 po 并编译 mo，返回 (新增数, 未翻译数)。"""
    import polib

    folder = I18N_DIR / locale / "LC_MESSAGES"
    folder.mkdir(parents=True, exist_ok=True)
    po_path = folder / "mcww.po"
    mo_path = folder / "mcww.mo"

    if po_path.exists():
        po = polib.pofile(str(po_path))
    else:
        po = polib.POFile()
        po.metadata = dict(PO_HEADER, Language=locale)

    seeds = TRANSLATIONS.get(locale, {})

    existing = {entry.msgid: entry for entry in po}
    added = 0
    for msgid in msgids:
        if msgid in existing:
            continue
        po.append(polib.POEntry(msgid=msgid, msgstr=seeds.get(msgid, "")))
        added += 1

    # 之前漏翻（空译文）但种子表里有译文的，顺手补上
    for entry in po:
        if entry.msgid in msgids and not entry.msgstr and seeds.get(entry.msgid):
            entry.msgstr = seeds[entry.msgid]

    # 源码里已经不再出现的词条没有保留价值
    kept = [entry for entry in po if entry.msgid in msgids and not entry.obsolete]
    for entry in po:
        if entry.msgid not in msgids:
            entry.obsolete = True
    del po[:]
    po.extend(kept)

    po.save(str(po_path))
    po.save_as_mofile(str(mo_path))

    untranslated = sum(1 for entry in kept if not entry.msgstr)
    return added, untranslated


def main():
    msgids = collect_msgids()
    if not msgids:
        print("没有扫描到任何 tr() 字面量，请检查 mcww/ui_*.py 是否存在。")
        return
    print(f"共 {len(msgids)} 条界面文案")
    for locale in LOCALES:
        try:
            added, untranslated = build_locale(locale, msgids)
        except ImportError:
            print("缺少 polib，无法编译 .mo：pip install polib")
            return
        print(f"  {locale}: 新增 {added} 条，待翻译 {untranslated} 条")


if __name__ == "__main__":
    main()
