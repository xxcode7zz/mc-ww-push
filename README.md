<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="200" alt="MC-WW logo"/>
    <br/>
    MC-WW
  </h1>

  <p>
    一个基于图像识别的鸣潮自动化程序，支持后台运行，基于 <a href="https://ok-script.com">ok-script</a> 框架开发。
    <br />
    代码与识别模板来自 <a href="https://github.com/ok-oldking/ok-wuthering-waves">ok-ww</a> 上游，可在线同步更新。
    <br />
    An image-recognition-based automation tool for Wuthering Waves, built on the <a href="https://ok-script.com">ok-script</a> framework.
  </p>

  <p><i>通过 Windows 接口模拟用户进行操作，无内存读取、无文件修改</i></p>
</div>

<!-- Badges -->
<div align="center">

![平台](https://img.shields.io/badge/platform-Windows-blue)

</div>

---

## ⚠️ 免责声明

本软件为外部辅助工具，旨在自动化《鸣潮》的部分游戏流程。它完全通过模拟常规用户界面与游戏交互，遵循相关法律法规。本项目旨在简化用户的重复性操作，不会破坏游戏平衡或提供不公平优势，也绝不会修改任何游戏文件或数据。

本软件开源、免费，仅供个人学习与交流使用，请勿用于任何商业或营利性目的。因使用本软件而产生的任何问题，均与开发者无关。

请注意，根据库洛官方的《鸣潮》公平运营声明：
> 严禁利用任何第三方工具破坏游戏体验。
> 我们将严厉打击使用外挂、加速器、作弊软件、宏脚本等违规工具的行为，这些行为包括但不限于自动挂机、技能加速、无敌模式、瞬移、修改游戏数据等操作。
> 一经查证，我们将视违规情况和次数，采取包括但不限于扣除违规收益、冻结或永久封禁游戏账号等措施。

**使用本软件即表示您已阅读、理解并同意以上声明，并自愿承担一切潜在风险。**

## ✨ 主要功能

*   **高分辨率支持**: 流畅运行于 4K 及以下所有 16:9 分辨率（最低 1280x720）。部分功能兼容 21:9 等超宽屏。
*   **后台模式**: 支持游戏窗口最小化或被遮挡时在后台运行，不影响您使用电脑。
*   **智能识别**: 全角色自动识别，无需手动配置技能序列，一键启动。
*   **自动静音**: 在后台运行时，可自动将游戏静音。
*   **上游同步**: 内置「上游同步（Upstream Sync）」页面，可在线检查并拉取 ok-ww 最新代码。
*   **角色代码**: 内置「角色代码（Character Code）」页面，可查看与修改角色战斗逻辑。

## 🔄 上游同步

MC-WW 与上游 ok-ww 的关系是**派生 + 同步**，不是一次性复制。程序内置同步引擎，可随时把上游最新代码拉到本地：

*   **同步路径**（每次同步由上游整体替换）：`src/`、`ok/`、`assets/`、`i18n/`、`pyappify/`、`requirements.txt` 等。上游新增任务、新增角色、修改识别模板都会自动带进来。
*   **受保护路径**（同步绝不覆盖）：`mcww/`（品牌层、自有页面、翻译词条）、`config.py`（品牌入口）、`main.py`、`pyappify.yml`、`icons/icon.png`、`icons/icon.ico`、`README.md`。
*   **安全保障**：同步前后对受保护路径做 MD5 校验，一旦发现被改动就整批回滚；同步前自动备份到 `backups/`，只保留最近 3 份，无实际改动时不占空间。
*   **两条通道，按实测速度排序**：CNB（`ok-ww-update2`，浅克隆整仓约 5 秒）优先，GitHub（`ok-ww-update`）兜底。国内网络下 GitHub 归档实测约 35 KB/s，同一个 46MB 代码树要跑二十多分钟，所以不作为首选。检查版本号时只读单文件 `config.py`，任意通道都在 1 秒内返回。
*   **首次同步实测**：v3.7.20 → v3.8.0 用时约 7 秒，受保护文件零改动。

用法：打开程序左侧「上游同步」→ 点「检查更新」看是否有新版本 → 点「立即同步」拉取 → 按提示重启程序生效。

> 同步只改代码，不自动重启。框架有单实例互斥，旧进程没退干净时新实例会被挡住，所以同步完成后请手动退出再重开。

## 🎭 角色代码

「角色代码」页面让你直接查看和编辑角色的战斗逻辑（技能循环、连招判定、 Buff 处理等）：

*   角色代码来自上游 `src/char/`，可直接在页面内编辑并保存到 `configs/custom_chars/`；
*   自定义代码优先级高于内置实现，上游更新不会覆盖你的改动；
*   可导出 / 导入自定义角色代码，便于分享与备份。

## 🔧 疑难解答 (Troubleshooting)

如果遇到问题，请在提问前按以下步骤逐一排查：

1.  **杀毒软件**：将软件的安装目录添加到您的杀毒软件（包括 Windows Defender）的**信任区或白名单**中，以防文件被误删或拦截。
2.  **显示设置**：
    *   一般可以开启游戏内滤镜。
    *   可以开启 Windows HDR，但必须关闭 Auto HDR（自动 HDR）。
    *   建议关闭显卡滤镜，例如 RTX HDR、RTX 动态亮丽（RTX Dynamic Vibrance）、AMD 锐化等。
    *   使用游戏默认的亮度设置。
    *   关闭任何在游戏画面上显示信息的叠加层（如 MSI Afterburner、Fraps 等显示的帧率）。
3.  **自定义按键**：如果您修改了游戏内的默认按键，请务必在 `MC-WW` 的设置中进行同步配置。仅支持设置中列出的按键。
4.  **软件版本**：在「上游同步」页检查并同步到最新代码。
5.  **游戏性能**：请确保游戏能稳定在 **60 FPS** 运行。如果帧率不稳定，请尝试降低游戏画质或分辨率。
6.  **游戏断线**：在 `MC-WW` 设置中开启“启动后关闭启动器”，确保启动器进程未在运行；或者使用源码运行。
7.  **OpenVINO 报错**：如果遇到 `0x000005` 报错，并且使用的是带 NPU 的 Intel CPU，请更新至 Intel 最新的 NPU 驱动。
8.  **上游已改名或移动模块**：如果「角色代码」页显示降级提示，说明上游把该模块改名了，请先在「上游同步」页同步，再查看 `logs/mc-ww.log` 定位原因。
9.  **关闭自动奔跑**：游戏设置里关闭自动奔跑。
10. **为所有角色装备主声骸**：队伍中的每个角色都必须装备主声骸（画面右下角应显示声骸技能图标）。任何一个角色未装备主声骸时，自动战斗将无法正常运行，并可能反复锁定敌人而不攻击。

---

## 💻 开发者专区

### 从源码运行

```powershell
# 建议使用项目本地虚拟环境
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

> 本工作副本的虚拟环境建在工作区根目录（`MC-WW/` 的上一级），所以本文所有命令
> 开头的 `.\.venv` 要写成 `..\.venv`。正常从仓库克隆下来时 `.venv` 就在项目根目录，
> 照抄即可。

### 命令行参数

您可以通过命令行参数实现自动化启动。

```powershell
# 示例：启动后自动执行第一个任务（一条龙），并在任务完成后退出程序
.\.venv\Scripts\python.exe main.py -t 1 -e
```

*   `-t` 或 `--task`: 启动后自动执行第 N 个任务。`1` 代表任务列表中的第一个。
*   `-e` 或 `--exit`: 任务执行完毕后自动退出程序。

### 发布仓库配置（双通道：CNB 国内优先，GitHub 保底）

打包器（pyappify）会用 `pyappify.yml` 里的 `git_url` 生成安装包的更新源。这个地址
和程序里「关于」页的仓库链接是同一个事实的两个消费者，所以**只有一处配置**：

```
mcww/release.json   # 唯一配置源（不要手改，用下面的脚本写）
    ↓ 自动同步
pyappify.yml        # 两个 profile 的 git_url
```

通道分工是写在代码里的（`mcww/release.py` 的 `CHANNEL_ORDER`），不是手工维护的约定：

| profile | 绑定 | 给谁用 |
|---|---|---|
| `China` | `cnb_url` | 国内网络，走 cnb.cool |
| `Global` | `github_url` | 海外网络，走 github.com |

一次写入两处，保证永远一致：

```powershell
.\.venv\Scripts\python.exe tools\set_repo.py --cnb https://cnb.cool/你的路径/mc-ww --github https://github.com/你的用户名/mc-ww
```

直接粘网页地址即可，脚本会自动补 `.git`。校验 / 清空：

```powershell
.\.venv\Scripts\python.exe tools\set_repo.py --check   # 绑定是否正确 + 仓库可达
.\.venv\Scripts\python.exe tools\check_release.py      # 发布前全面检查（静态，不用 Qt）
.\.venv\Scripts\python.exe tools\set_repo.py --clear   # 清空（回到未配置状态）
```

地址留空时程序照常本地运行（链接回退到上游说明页），但发版检查会拒绝打 tag ——
避免发出一个更新必然 404 的安装包。也可以用环境变量 `MC_WW_CNB_URL` /
`MC_WW_GITHUB_URL` 临时覆盖，不落盘。

`tools/check_release.py` 分两档，这是有意的：普通 push 时配置缺失只警告（仓库刚
建、地址还没填的阶段不该每次 push 都红），带上 `--tag` 才是发版检查，配置缺失直接
判失败。

### 发布新版本

一个 git tag = 一个可安装版本。pyappify 会把该 tag 的整棵工作树拉下来覆盖安装，
所以 tag 内容必须就是当前主干的内容：

```powershell
# 1) 演练：跑检查 + 打印要执行的命令，不联网、不打 tag
.\.venv\Scripts\python.exe tools\publish.py v1.0.0 --dry-run

# 2) 真发布（CNB 优先，失败或未配自动降级到 GitHub）
$env:MC_WW_CNB_TOKEN    = "你的 CNB 访问令牌"      # 用户名固定为 cnb
$env:MC_WW_GITHUB_TOKEN = "你的 GitHub PAT"        # 需要 repo 权限
.\.venv\Scripts\python.exe tools\publish.py v1.0.0

# 只推单个通道 / 查看状态
.\.venv\Scripts\python.exe tools\publish.py --only cnb
.\.venv\Scripts\python.exe tools\publish.py --list
```

令牌**只从环境变量读**，脚本不写 remote、不写 credential 文件、输出时打码。
CNB 访问令牌在「个人设置 → 访问令牌」生成（需 `repo-contents` 读写权限），
GitHub 在 Settings → Developer settings → Personal access tokens 生成。

推 tag 之后 CNB 会触发 `.cnb.yml` 里的发版流水线：校验 → 用 `git archive` 打包 →
建 Release → 用 `cnbcool/attachments` 挂附件。附件地址形如
`https://cnb.cool/<组>/<仓库>/-/releases/download/v1.0.0/MC-WW-v1.0.0.zip`。

### 目录结构与同步边界

```
MC-WW/
├── main.py               # 启动入口（调用 bootstrap 后启动 OK）
├── config.py             # 【受保护】品牌入口，导入 upstream_config 并改写品牌
├── upstream_config.py    # 【同步】上游原始 config.py
├── LICENSE.txt           # 【受保护】AGPL-3.0 许可证全文
├── .cnb.yml              # CNB 流水线（push 检查 / tag 发版）
├── mcww/                 # 【受保护】MC-WW 自有代码
│   ├── branding.py       #   品牌改写、运行时补丁、翻译回退
│   ├── release.py        #   双通道地址、优先级、可达性探测
│   ├── release.json      #   地址唯一配置源（tools/set_repo.py 写入）
│   ├── sync_engine.py    #   上游同步引擎（下载/替换/校验/回滚）
│   ├── ui_sync_tab.py    #   「上游同步」页面
│   ├── ui_char_code_tab.py # 「角色代码」页面
│   ├── i18n_build.py     #   MC-WW 自有词条构建脚本
│   └── i18n/             #   自有翻译（zh_CN / zh_TW）
├── tools/                # 【受保护】维护脚本
│   ├── set_repo.py       #   写入双通道地址（同步 json 与 pyappify.yml）
│   ├── check_release.py  #   发布前检查（静态，可在裸 python 镜像跑）
│   └── publish.py        #   打 tag 并推送（CNB 优先、GitHub 保底）
├── src/                  # 【同步】上游任务与角色代码
├── ok/                   # 【同步】ok-script 框架
├── assets/               # 【同步】识别模板
├── i18n/                 # 【同步】上游翻译
├── icons/                # icon.png / icon.ico 受保护，任务图标可同步
└── backups/              # 同步前自动备份（已 gitignore）
```

改代码前请先看这张表：**改 `src/` 里的东西会在下次同步时丢失**，需要长期保留的逻辑请放进 `mcww/`，或用 `mcww/branding.py` 的运行时补丁挂上去。

### 维护 MC-WW 自有翻译

新增 `mcww/ui_*.py` 里的 `self.tr("...")` 文案后，重跑构建脚本即可更新 `.po` / `.mo`：

```powershell
.\.venv\Scripts\python.exe -m mcww.i18n_build
```

脚本会保留已有译文、补入新词条、清掉源码里已删除的条目。

## ❤️ 致谢

MC-WW 基于以下开源项目，遵循上游 AGPL-3.0 许可证：

*   [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) — 上游主体，任务逻辑、角色代码与识别模板均来自这里
*   [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) — 自动化框架
*   [lazydog28/mc_auto_boss](https://github.com/lazydog28/mc_auto_boss)
*   [ok-oldking/OnnxOCR](https://github.com/ok-oldking/OnnxOCR)
*   [zhiyiYo/PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
*   [Toufool/AutoSplit](https://github.com/Toufool/AutoSplit)

上游代码版权归 ok-ww 作者所有。本项目的品牌层（`mcww/`）与自有页面由 MC-WW 维护。
