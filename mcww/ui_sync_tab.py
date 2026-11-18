"""MC-WW 上游同步页。

这一页负责「MC-WW 能在线连接 OK-WW，并在上游更新时及时更新代码」这条需求：

* 显示本地与上游版本、上次同步时间与来源；
* 一键检查上游版本（只读上游 config.py，几百毫秒）；
* 一键同步（下载上游压缩包 → 替换同步路径 → 校验受保护文件 → 失败自动回滚）；
* 可选「启动时检查」，发现新版本时只在界面提示，不擅自改动代码。

同步引擎在 :mod:`mcww.sync_engine`，本模块只做界面与线程调度。
文案用英文 msgid，中文由 ``mcww/i18n`` 词条提供 —— 上游 ``i18n/`` 属于同步
路径，把中文写死在源码里会随上游更新一起被替换掉。
"""

import inspect
import json
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ok import Logger
from ok.ui.qt.kit.buttons import Button
from ok.ui.qt.kit.cards import SettingGroup, SettingRow
from ok.ui.qt.kit.feedback import show_toast
from ok.ui.qt.kit.labels import Label
from ok.ui.qt.kit.switch import Switch
from ok.ui.qt.widget.CustomTab import CustomTab

from mcww import release
from mcww.branding import APP_NAME, APP_ROOT, PACKAGE_DIR
from mcww.sync_engine import SYNC_SOURCES, SyncEngine, load_state

logger = Logger.get_logger(__name__)

# 同一次运行里不重复打上游接口，避免被当成刷流量
AUTO_CHECK_INTERVAL = 3600


class _Settings:
    """把「启动时检查」这类开关落到受保护的 ``mcww/`` 目录，重启后仍有效。"""

    FILE = PACKAGE_DIR / "ui_settings.json"

    def __init__(self):
        self._data = {}
        try:
            data = json.loads(self.FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._data = data
        except Exception:
            self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        try:
            self.FILE.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            logger.warning(f"保存 MC-WW 界面设置失败: {error}")


_settings = _Settings()
_last_auto_check = 0.0


def _has_cjk(text: str) -> bool:
    """文本里有没有汉字。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


def _join_paths(paths, cjk: bool) -> str:
    """按界面语言拼接路径列表。"""
    return ("、" if cjk else ", ").join(paths)


def _format_source_line(name: str, url: str, cjk: bool) -> str:
    """「• 名称：地址」这种资源行，冒号也要跟着语言走。"""
    return f"• {name}{'：' if cjk else ': '}{url}"


def upstream_status() -> dict:
    """给启动流程或其它页面读的只读状态快照。"""
    state = load_state(APP_ROOT)
    return {
        "version": state.get("upstream_version", ""),
        "previous_version": state.get("previous_version", ""),
        "synced_at": state.get("synced_at", ""),
        "source": state.get("source", ""),
    }


class McWwSyncTab(CustomTab):
    """「Upstream Sync」页。"""

    def __init__(self):
        super().__init__()
        self._busy = False
        # 同步开始前的上游版本。同步完成后用它算出「v3.8.3 → v3.8.5」这种
        # 前后对比 —— 只说「已同步至 X」时，用户看不出到底有没有变。
        self._prev_version = ""
        # 最近一次检查更新的结果里有新版本时置位，同步完成后清掉。
        self._pending_version = ""
        # 操作序号。同步和检查都在后台跑，谁先返回不由点击顺序决定：
        # 启动时的自动检查比手动同步早发出、却常常更晚返回，于是同步刚写下
        # 「已更新」，就被那条迟到的检查结果覆盖成「已是最新」—— 看起来就像
        # 同步没成功。用递增序号认领结果，迟到的旧操作只允许恢复按钮状态，
        # 不许再改文案。
        self._op_seq = 0

        header = QWidget(self.view)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = Label(self.tr("Upstream Sync"), "subtitle", header)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        self.check_button = Button(self.tr("Check for Updates"), icon="refresh", parent=header)
        self.check_button.clicked.connect(self._check_clicked)
        header_layout.addWidget(self.check_button)
        self.sync_button = Button(self.tr("Sync Now"), icon="download", variant="primary", parent=header)
        self.sync_button.clicked.connect(self._sync_clicked)
        header_layout.addWidget(self.sync_button)
        self.add_widget(header)

        status_widget = QWidget(self.view)
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        self.status_label = Label("", "body", status_widget, word_wrap=True)
        status_layout.addWidget(self.status_label)
        self.hint_label = Label("", "secondary", status_widget, word_wrap=True)
        status_layout.addWidget(self.hint_label)
        self.add_card(self.tr("Version Status"), status_widget)

        self.auto_switch = Switch(bool(_settings.get("auto_check", True)))
        self.auto_switch.toggled.connect(self._auto_check_changed)
        group = SettingGroup(self.tr("Sync Settings"))
        group.add_row(SettingRow(
            self.tr("Check upstream on startup"),
            self.tr("Checks the upstream version quietly after startup and shows a hint "
                    "when a newer version exists. It never changes code on its own."),
            self.auto_switch,
        ))
        self.add_card("", group)

        source_widget = QWidget(self.view)
        source_layout = QVBoxLayout(source_widget)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        # 冒号跟着界面实际语言走，见 _has_cjk 的说明
        sources_cjk = _has_cjk(SYNC_SOURCES[0]["name"] if SYNC_SOURCES else "")
        for source in SYNC_SOURCES:
            source_layout.addWidget(Label(
                _format_source_line(source["name"], source["git_url"], sources_cjk), "secondary",
                source_widget, word_wrap=True))
        source_layout.addWidget(Label(
            self.tr("Syncing replaces upstream code only (src / ok / assets / i18n and so on). "
                    "MC-WW branding and its own pages are never overwritten, and a failed "
                    "check rolls everything back."),
            "caption", source_widget, word_wrap=True))
        self.add_card(self.tr("Upstream Sources"), source_widget)

        # 显示 MC-WW 自己的发布仓库配置状态 —— 空的话在界面上就能看见，
        # 不用等到打包时才发现地址没填。
        release_widget = QWidget(self.view)
        release_layout = QVBoxLayout(release_widget)
        release_layout.setContentsMargins(0, 0, 0, 0)
        release_layout.setSpacing(6)
        channels = release.configured_channels()
        if channels:
            # 顺序即优先级：CNB 在国内优先，GitHub 保底
            for index, (channel, url) in enumerate(channels):
                label = release.CHANNEL_LABELS.get(channel, channel)
                if index == 0:
                    role = self.tr("primary")
                else:
                    role = self.tr("fallback")
                release_layout.addWidget(Label(
                    _format_source_line(
                        f"{label}（{role}）" if _has_cjk(role) else f"{label} ({role})",
                        url, _has_cjk(role)),
                    "secondary", release_widget, word_wrap=True))
            download = release.download_url()
            if download:
                release_layout.addWidget(Label(
                    f"{self.tr('Releases')}: {download}", "secondary",
                    release_widget, word_wrap=True))
            if len(channels) == 1:
                release_layout.addWidget(Label(
                    self.tr("Only one channel is configured. Add the other one as a mirror: "
                            "python tools/set_repo.py --cnb <url> --github <url>"),
                    "caption", release_widget, word_wrap=True))
        else:
            release_layout.addWidget(Label(
                self.tr("No release repository configured yet — the app runs locally, "
                        "but packaging needs one. Run: "
                        "python tools/set_repo.py --cnb <url> --github <url>"),
                "secondary", release_widget, word_wrap=True))
        self.add_card(self.tr("Release Repository"), release_widget)


        self._refresh_status()
        QTimer.singleShot(0, self._auto_check_once)

    # ------------------------------------------------------------ 基本信息

    @property
    def name(self):
        return self.tr("Upstream Sync")

    @property
    def icon(self):
        # 用语义枚举而不是字符串 "sync"：内置图标名里没有 sync，
        # nav_icon() 遇到未知字符串会静默回退成 grid，侧边栏图标就不对了。
        from ok.core.icons import Icon
        return Icon.SYNC

    def _auto_check_changed(self, checked):
        _settings.set("auto_check", bool(checked))

    def _refresh_status(self):
        status = upstream_status()
        if not status["version"]:
            self.status_label.setText(
                self.tr("Not synced yet — currently running on the bundled baseline."))
            self.hint_label.setText(self.tr("Click \"Sync Now\" to pull the latest ok-ww code."))
            return
        # 版本有跳变时把「旧 → 新」写进状态行：重启后用户最想确认的就是
        # 「我上次同步到底把版本升上去了没有」，只显示当前值说明不了这件事。
        previous = status["previous_version"]
        if previous and previous != status["version"]:
            self.status_label.setText(
                self.tr("Local upstream version: {version} (updated from {previous})").format(
                    version=status["version"], previous=previous))
        else:
            self.status_label.setText(
                self.tr("Local upstream version: {version}").format(version=status["version"]))
        detail = []
        if status["synced_at"]:
            detail.append(self.tr("Last sync: {time}").format(time=status["synced_at"]))
        if status["source"]:
            detail.append(self.tr("Source: {source}").format(source=status["source"]))
        self.hint_label.setText("　".join(detail))

    # ------------------------------------------------------------ 自动检查

    def _auto_check_once(self):
        """启动后静默检查一次，只提示，不动代码。"""
        global _last_auto_check
        if not _settings.get("auto_check", True):
            return
        if time.time() - _last_auto_check < AUTO_CHECK_INTERVAL:
            return
        _last_auto_check = time.time()
        self._run_in_background(self._check_worker,
                                self._bind(self._on_check_done), silent=True)

    # ------------------------------------------------------------ 检查更新

    def _check_clicked(self):
        self.check_button.setEnabled(False)
        self._run_in_background(self._check_worker, self._bind(self._on_check_done))

    def _bind(self, callback):
        """给回调盖一个操作序号，返回只接受 ``result``（和 ``silent``）的包装。

        包装后回调签名固定为 ``(result, silent=False)``，与
        ``_run_in_background`` 的派发约定一致，不必再靠 ``_accepts_silent``
        猜参数个数；同时把「这次结果还该不该上屏」的判断收进一处。
        """
        self._op_seq += 1
        seq = self._op_seq

        def wrapper(result, silent=False):
            if seq != self._op_seq:
                # 有更新的操作已经发出，本次结果只用于恢复按钮，不改文案。
                logger.info("忽略过期结果（本次操作已被更新的操作取代）")
                self._restore_buttons()
                return
            # 内层回调的形参个数不统一（_on_check_done 收 silent，
            # _on_sync_done 不收），这里同样按签名派发。
            if _accepts_silent(callback):
                callback(result, silent)
            else:
                callback(result)

        return wrapper

    def _restore_buttons(self):
        if not self._busy:
            self.sync_button.setEnabled(True)
        self.check_button.setEnabled(True)

    def _check_worker(self):
        return SyncEngine(APP_ROOT).check_upstream(timeout=30)

    def _on_check_done(self, result, silent=False):
        self.check_button.setEnabled(True)
        if not result.get("ok"):
            if not silent:
                show_toast(self, self.tr("Check failed: {error}").format(
                    error=result.get("error", "")), tone="danger")
            return
        version = result.get("version", "")
        local = result.get("local_version", "")
        if result.get("updated"):
            self._pending_version = version
            self.status_label.setText(
                self.tr("New upstream version found: {version} (local {local})").format(
                    version=version, local=local))
            self.hint_label.setText(self.tr("Click \"Sync Now\" to update to it."))
        else:
            self._pending_version = ""
            self.status_label.setText(
                self.tr("Already up to date: {version}").format(version=version or local))
            self.hint_label.setText(self.tr("Source: {source}").format(
                source=result.get("source", "")))
        if not silent:
            show_toast(self, self.tr("Check finished"), tone="success")

    # ------------------------------------------------------------ 执行同步

    def _sync_clicked(self):
        if self._busy:
            return
        self._busy = True
        # 记下同步前的版本，完成时才能显示「旧 → 新」的变化
        self._prev_version = upstream_status()["version"]
        self.sync_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.status_label.setText(self.tr("Syncing upstream code, please wait…"))
        self.hint_label.setText(self.tr("Download → replace → verify. The window may freeze briefly."))
        self._run_in_background(self._sync_worker, self._bind(self._on_sync_done))

    def _sync_worker(self):
        return SyncEngine(APP_ROOT).sync()

    def _on_sync_done(self, result):
        self._busy = False
        self.sync_button.setEnabled(True)
        self.check_button.setEnabled(True)
        previous = self._prev_version
        self._prev_version = ""
        if not result.get("ok"):
            self.status_label.setText(self.tr("Sync failed"))
            self.hint_label.setText(result.get("error", ""))
            show_toast(self, self.tr("Sync failed: {error}").format(
                error=result.get("error", "")), tone="danger", duration=8000)
            return

        version = result.get("version", "")
        changed = result.get("changed_paths") or []
        rescued = result.get("rescued_paths") or []
        self._pending_version = ""

        # 同步完成必须**明确**告诉用户结果，两种情形分开说：
        # 有改动 → 「已更新到 X」并列出路径，提示重启；
        # 无改动 → 「已是最新」且明确说不用重启。
        # 原先无论有没有改动都显示 "Updated paths: none. Restart to apply"，
        # 前后矛盾 —— 什么都没换却让人重启，用户会以为同步没生效。
        #
        # 「有改动」要把 rescued 算进去：上游删了文件、我们把它留下，
        # 这同样是本地状态的改变，只说「已是最新」会让用户以为什么都没发生、
        # 功能却凭空少了一块（这正是角色代码编辑器消失时的表现）。
        if changed or rescued:
            jumped = previous and version and previous != version
            if jumped:
                self.status_label.setText(
                    self.tr("Updated: {previous} → {version}").format(
                        previous=previous, version=version))
            else:
                self.status_label.setText(
                    self.tr("Synced to upstream {version}").format(version=version))

            # 两句话分开写，因为原因不同、用户要采取的动作也不同。
            # 标点按**译文**判断而不是按语言配置：.mo 没加载成功时界面显示
            # 英文 msgid，此时若还按配置补中文顿号，就成了中英混排的
            # 「Updated from upstream: src、icons」。
            updated_tpl = self.tr("Updated from upstream: {paths}")
            kept_tpl = self.tr("Kept locally (removed upstream): {paths}")
            restart_tpl = self.tr("Restart {app} to apply.")
            cjk = _has_cjk(updated_tpl + kept_tpl + restart_tpl)
            parts = []
            if changed:
                parts.append(updated_tpl.format(paths=_join_paths(changed, cjk)))
            if rescued:
                parts.append(kept_tpl.format(paths=_join_paths(rescued, cjk)))
            parts.append(restart_tpl.format(app=APP_NAME))
            # 分句符跟着语言走：中文用「。」，英文用空格。
            # 尾终止符只在文本还没结束时才补 —— 英文 msgid 自带「.」，
            # 无条件补会输出「to apply..」。
            sep = "。" if cjk else " "
            text = sep.join(parts)
            if not text.endswith(("。", ".", "！", "!", "？", "?")):
                text += "。" if cjk else "."
            self.hint_label.setText(text)
            show_toast(
                self, self.tr("Sync finished — restart {app} to apply").format(app=APP_NAME),
                tone="success", duration=8000,
                action=(self.tr("Quit Now"), self._quit_app),
            )
        else:
            self.status_label.setText(
                self.tr("Already up to date: {version}").format(version=version or previous))
            self.hint_label.setText(
                self.tr("Nothing to sync — no files differ from upstream. No restart needed."))
            show_toast(self, self.tr("Already up to date"), tone="neutral", duration=5000)

        # 同步刚结束时用户最想看的是「这次成没成、变了什么」，所以上面两行
        # 保留结果文案，不调 _refresh_status 覆盖掉。「上次同步」时间会在
        # 下次进入本页或点「检查更新」时更新，两者信息不冲突。
        logger.info(
            f"同步完成：{previous or '(未知)'} → {version or '(未知)'}，"
            f"来源 {result.get('source', '')}，变更 {len(changed)} 项"
            + (f"：{', '.join(changed)}" if changed else "（无改动）")
            + (f"，本地保留 {len(rescued)} 项：{', '.join(rescued)}" if rescued else "")
        )

    @staticmethod
    def _quit_app():
        """退出程序，让用户重开。

        不在旧进程里自动拉起新实例：框架有单实例互斥（``ok/util/process.py``），
        旧进程没退干净时新实例会被挡住，反而更糟。
        """
        try:
            from ok.core.events import communicate
            communicate.quit.emit()
        except Exception as error:
            logger.warning(f"退出程序失败: {error}")

    # ------------------------------------------------------------ 线程封装

    def _run_in_background(self, worker, on_done, silent=False):
        """在后台线程跑阻塞任务，主线程用 QTimer 轮询结果。

        不用跨线程 signal：回调只是刷新几个 label，轮询更简单，也省掉元类型注册。
        """
        box = {}

        def run():
            try:
                box["result"] = worker()
            except Exception as error:  # 后台异常也要变成界面提示，不能静默失败
                logger.error(f"MC-WW 后台任务失败: {error}")
                box["result"] = {"ok": False, "error": str(error)}

        thread = threading.Thread(target=run, daemon=True, name="MCWW-UiTask")
        thread.start()

        timer = QTimer(self)
        timer.setInterval(150)

        def poll():
            if thread.is_alive():
                return
            timer.stop()
            timer.deleteLater()
            result = box.get("result") or {"ok": False, "error": "task returned nothing"}
            # 按回调实际接收的参数个数派发。原先这里固定传 ``(result, silent)``，
            # 而 ``_on_sync_done`` 只声明了一个形参，QTimer 里抛出的 TypeError
            # 会被 Qt 吞成一条 "Uncaught exception" 日志 —— 界面既不报错也不刷新，
            # 按钮永久停在禁用态。改成自适应后，加回调不必再记着这条隐式约定。
            try:
                if _accepts_silent(on_done):
                    on_done(result, silent)
                else:
                    on_done(result)
            except Exception:
                # 回调里的异常如果逃进事件循环，只会留下一条没人看的日志，
                # 界面就停在「正在同步」上。这里显式兜住：完整堆栈进日志，
                # 并且一定把按钮恢复，保证界面不会永久卡死。
                logger.exception("MC-WW 完成回调执行失败")
                self._restore_buttons()
                self.status_label.setText(self.tr("Sync failed: {error}").format(
                    error=self.tr("unexpected error, see the log")))

        timer.timeout.connect(poll)
        timer.start()


def _accepts_silent(callback):
    """回调是否接收第二个 ``silent`` 位置参数。"""
    try:
        params = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return True  # 内建/C 函数拿不到签名，按旧约定传
    positional = [
        p for p in params.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if any(p.kind is p.VAR_POSITIONAL for p in params.values()):
        return True
    return len(positional) >= 2
