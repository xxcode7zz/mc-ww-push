"""MC-WW 配置入口。

结构说明（这是同步设计的一部分）：

* ``upstream_config.py`` 是 ok-ww 上游的原始配置，属于**同步路径**，
  每次同步都会被上游最新版本整体替换 —— 所以上游新增任务、改按键、
  改识别参数，都会自动出现在 MC-WW 里。
* 本文件属于**受保护路径**，同步不会动它，它只做一件事：
  导入上游基线，然后交给 :func:`mcww.branding.apply_brand` 改写品牌信息。

因此对外导出的仍然是 ``config`` 这个名字，``from config import config``
的所有上游代码都不需要改。
"""

from mcww.branding import apply_brand

from upstream_config import config as _upstream_config

config = apply_brand(_upstream_config)

# 上游把 version 写在模块级变量上，这里同步转发一份，方便外部读版本号。
from upstream_config import version  # noqa: E402

__all__ = ["config", "version"]
