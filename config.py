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

# 版本号：以品牌层 ``mcww.branding.APP_VERSION`` 为准（upstream_config 里那个
# 是上游版本，如 v3.8.0，外部读到会误以为是 ok-ww）。
#
# 打包注意：CI 里的 ``ok.update.inline_ok_requirements`` 用正则把本文件里
# 「version 后跟等号再跟一对引号」的赋值统一替换成 tag 值，**连注释一起改**。
# 所以这里两件事必须做到：
#
# 1. 赋值行写成字面字符串，才能被正则命中、打包时写进正确版本号；
# 2. 注释里不要出现那个赋值的完整字面形式，否则会连带被替换成版本号。
#
# 下面这行的字面形状是打包链路的一部分，改成表达式会让版本号静默失效。
version = "v1.0.0"

__all__ = ["config", "version"]
