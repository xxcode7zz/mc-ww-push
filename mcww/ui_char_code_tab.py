"""MC-WW 角色代码页。

「MC-WW 需要有能修改角色代码的功能」这条需求由本页承载。

上游 ``src/gui/CharacterCodeTab.py``（约 1900 行）已经实现了完整的角色代码
编辑器：队伍列表、内置/自定义代码切换、差异对比、导入导出队伍、代码工坊
下载、代码高亮等。**这里不复制它的实现**，而是直接继承：

* 上游属于同步路径，每次同步都会被整体替换。复制一份就等于把上游的每次
  改进都挡在门外，还要长期手工合并。
* 继承则相反：上游改了编辑器逻辑、修了 bug、加了功能，MC-WW 下次同步就
  自动拿到，一行都不用跟。

本模块只做两件上游不该管的事：

1. 把页面注册进 MC-WW 的配置（见 :func:`mcww.branding.apply_brand`），
   因为上游发布版故意没有注册这个页面；
2. 给页面套上 MC-WW 的品牌（标题、图标、贡献链接）。

如果哪天上游把这个文件删了或改了类名，本模块会退化成一张说明页而不是
让整个程序启动失败 —— 见 :class:`_UnavailableTab`。
"""

from ok import Logger
from ok.ui.qt.kit.buttons import Button
from ok.ui.qt.kit.feedback import show_toast
from ok.ui.qt.kit.labels import Label
from ok.ui.qt.widget.CustomTab import CustomTab

from mcww.branding import APP_NAME

logger = Logger.get_logger(__name__)


def _upstream_tab_class():
    """取上游角色代码页的类，取不到返回 ``None``。"""
    try:
        from src.gui.CharacterCodeTab import CharacterCodeTab
        return CharacterCodeTab
    except Exception as error:  # 上游改名/删文件都不该阻断启动
        logger.warning(f"无法加载上游角色代码页，将使用降级页面: {error}")
        return None


_Upstream = _upstream_tab_class()


if _Upstream is not None:

    class McWwCharacterCodeTab(_Upstream):
        """上游角色代码页，标题与品牌换成 MC-WW 的。"""

        @property
        def name(self):
            return self.tr("Character Code")

        @property
        def icon(self):
            from ok.ui.qt.kit.icons import icon as kit_icon
            return kit_icon("code")

else:

    class McWwCharacterCodeTab(CustomTab):
        """降级页：上游角色代码页不可用时给出可操作的提示。"""

        def __init__(self):
            super().__init__()
            self.add_card(self.tr("Character Code"), self._build_body())

        @property
        def name(self):
            return self.tr("Character Code")

        @property
        def icon(self):
            return "code"

        def _build_body(self):
            from PySide6.QtWidgets import QVBoxLayout, QWidget

            body = QWidget(self.view)
            layout = QVBoxLayout(body)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(Label(
                self.tr("The character code editor from {app}'s upstream is missing, "
                        "most likely because upstream renamed or moved it.").format(app=APP_NAME),
                "body", body, word_wrap=True))
            layout.addWidget(Label(
                self.tr("Try syncing upstream first. If it still fails, open an issue with "
                        "the log attached."),
                "secondary", body, word_wrap=True))

            button = Button(self.tr("Open Upstream Sync"), icon="sync", variant="primary", parent=body)
            button.clicked.connect(self._goto_sync_tab)
            layout.addWidget(button)
            return body

        def _goto_sync_tab(self):
            try:
                from ok import og
                window = og.ok.main_window
                page = getattr(window, "_pages", {}).get("McWwSyncTab")
                if page is not None:
                    window.switch_to(page)
                    return
            except Exception as error:
                logger.warning(f"跳转同步页失败: {error}")
            show_toast(self, self.tr("Please open the Upstream Sync page manually."), tone="warning")
