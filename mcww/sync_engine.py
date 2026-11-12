"""MC-WW 上游同步引擎。

职责：把 ok-ww 上游仓库（运行版）的代码拉到本地 MC-WW 目录，并且**永远不覆盖
MC-WW 自己的东西**。

同步边界（这是整个设计的关键）：

* ``SYNC_PATHS`` 里的路径完全由上游控制，每次同步整体替换 —— 上游新增任务、
  新增角色、修改识别模板都能第一时间带进来。
* ``SYNC_FILE_MAP`` 处理"上游文件名与 MC-WW 不同"的少数情况：上游的
  ``config.py`` 落到本地的 ``upstream_config.py``，本地 ``config.py`` 则是
  受保护的品牌入口。
* ``PROTECTED_PATHS`` 是 MC-WW 的品牌与功能层，同步前后做哈希校验，
  一旦发现被改动就整批回滚。
* ``icons/`` 只同步上游新增的任务图标，绝不动 ``icon.png`` / ``icon.ico``。

网络通道：先 GitHub / CNB 的 codeload 压缩包（本项目唯一必需能力），
失败再退到 dulwich 浅克隆读取工作树。全程不需要系统 git。
"""

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from ok import Logger

logger = Logger.get_logger(__name__)

# ---------------------------------------------------------------- 同步配置

# 上游运行版仓库（按优先级尝试）。
#
# 顺序按**实测速度**排，不是按"哪个更知名"排：同一个 46MB 的上游代码树，
# CNB 浅克隆 5.5s，GitHub codeload 只有约 35KB/s（要二十多分钟）。
# 国内网络下先试 GitHub 等于让用户等十几分钟才开始同步，所以国内通道放第一位。
#
# * CNB 是完整仓库（762 个条目，含 src/ok/assets/config.py），走 dulwich 浅克隆；
#   它的默认分支是 ``main``（曾错写成 master，会导致 clone 直接 ValueError）。
# * GitHub 有 codeload 压缩包和 raw 单文件接口，单文件探测版本号最快，
#   所以 ``check_upstream()`` 仍优先用它，但整包同步排在国内通道之后。
SYNC_SOURCES = [
    {
        "name": "CNB 国内镜像",
        "git_url": "https://cnb.cool/ok-oldking/ok-ww-update2.git",
        "branch": "main",
        # CNB 的 /-/archive/*.tar.gz 只回单个文件而不是打包结果，实测不可用，
        # 因此这里不配 tarball，走 git 协议浅克隆。
    },
    {
        "name": "GitHub",
        "git_url": "https://github.com/ok-oldking/ok-ww-update",
        "branch": "main",
        "tarball": "https://codeload.github.com/ok-oldking/ok-ww-update/tar.gz/refs/heads/main",
        "raw": "https://raw.githubusercontent.com/ok-oldking/ok-ww-update/main/config.py",
    },
]

# 版本号探测专用顺序：单文件 raw 接口比克隆快一个数量级，不受上面的整包顺序影响。
VERSION_SOURCES = list(SYNC_SOURCES)

# 完全跟随上游的路径（整体替换）
SYNC_PATHS = [
    "assets",
    "i18n",
    "ok",
    "src",
    "pyappify",
    "ok_templates",
    "requirements.txt",
    "main_web.py",
    "main_web_debug.py",
]

# 上游文件名 -> 本地文件名（少数需要改名才能共存的文件）
SYNC_FILE_MAP = {
    "config.py": "upstream_config.py",
}

# MC-WW 自有文件：同步前后做哈希校验，绝不参与替换
PROTECTED_PATHS = [
    "config.py",
    "mcww",
    "tools",
    "main.py",
    "main_debug.py",
    "pyappify.yml",
    "icons/icon.png",
    "icons/icon.ico",
    "README.md",
    "LICENSE.txt",
]

# icons/ 下只允许替换任务图标，品牌图标单独保护
BRAND_ICONS = ("icon.png", "icon.ico")

STATE_FILE = "mcww/sync_state.json"

# 备份目录必须落在受保护路径**之外**：受保护路径靠哈希校验，
# 备份本身写进去会让哈希必然变化，导致每次同步都被判成污染。
BACKUP_DIR = "backups"

# 备份保留份数。每份约 46MB（整份 src/ok/assets 副本），留 3 份够回滚，
# 再多就是纯粹占磁盘。
BACKUP_KEEP = 3

# 哈希时忽略的路径片段：状态文件每次同步都会变，字节码缓存随时会变，
# 都不该计入目录指纹，否则受保护校验会误报。
IGNORED_PARTS = {"__pycache__", ".pyc", "sync_state.json"}

USER_AGENT = "MC-WW-Updater/1.0"


class SyncError(Exception):
    """同步失败，携带可直接展示给用户的中文原因。"""


class _QuietStream:
    """吞掉 dulwich 的进度输出，避免几万行噪声淹没日志。"""

    def write(self, *_args, **_kwargs):
        return None

    def flush(self):
        return None

    def isatty(self):
        return False


# ---------------------------------------------------------------- 状态读写


def _md5(path: Path) -> str:
    """对文件或目录做稳定哈希，用来判断内容是否变化。

    目录哈希会跳过 ``__pycache__`` 和同步状态文件：前者是运行时产物，
    后者每次同步都会重写，把它们算进指纹会让受保护校验永远不通过。
    """
    if path.is_file():
        return hashlib.md5(path.read_bytes()).hexdigest()
    if path.is_dir():
        digest = hashlib.md5()
        for item in sorted(path.rglob("*")):
            if not item.is_file():
                continue
            if any(part in IGNORED_PARTS for part in item.relative_to(path).parts):
                continue
            digest.update(str(item.relative_to(path)).replace("\\", "/").encode("utf-8"))
            digest.update(item.read_bytes())
        return digest.hexdigest()
    return ""


def load_state(app_dir: Path) -> dict:
    """读取同步状态；文件损坏时返回空状态而不是抛错。"""
    state_path = Path(app_dir) / STATE_FILE
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                state.setdefault("history", [])
                return state
        except (OSError, ValueError) as error:
            logger.warning(f"读取同步状态失败: {error!r}")
    return {
        "upstream_version": "",
        "upstream_commit": "",
        "synced_at": "",
        "source": "",
        "history": [],
    }


def save_state(app_dir: Path, state: dict) -> None:
    state_path = Path(app_dir) / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 下载上游


def _http_get(url: str, timeout: int):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def _download_tarball(url: str, timeout: int = 180) -> Path:
    """下载上游压缩包到临时目录，返回本地路径。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="mcww_sync_"))
    archive = tmp_dir / "upstream.tar.gz"
    try:
        with _http_get(url, timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise SyncError(f"HTTP {response.status}")
            with archive.open("wb") as out:
                shutil.copyfileobj(response, out, length=1 << 20)
        if archive.stat().st_size < 1024:
            raise SyncError("下载内容为空")
    except Exception as error:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise SyncError(f"下载上游失败：{error}") from error
    return archive


def _extract_tarball(archive: Path) -> Path:
    """解压压缩包，返回唯一的顶层目录。"""
    extract_to = archive.parent / "extracted"
    extract_root = extract_to.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        # 防路径穿越：成员只允许落在解压目录内
        for member in tar.getmembers():
            target = (extract_to / member.name).resolve()
            if target != extract_root and extract_root not in target.parents:
                raise SyncError(f"上游压缩包包含非法路径 {member.name}，已中止同步")
        tar.extractall(extract_to)
    children = [item for item in extract_to.iterdir() if item.is_dir()]
    if len(children) != 1:
        raise SyncError("上游压缩包结构异常，未找到唯一根目录")
    return children[0]


def _clone_shallow(source: dict, timeout: int) -> tuple:
    """国内通道：dulwich 浅克隆并真正检出工作树（无需系统 git）。

    返回 ``(工作树目录, 待清理的临时目录)``。

    两个踩过的坑：

    * 不能用 ``bare=True`` 再自己 ``build_index_from_tree`` —— 那只写出了一个
      ``index`` 文件，工作树里没有实体代码，同步过去等于把 ``src/`` 清空。
      直接非 bare 克隆，dulwich 会自己把文件 checkout 出来（实测 5.5s / 46MB）。
    * ``branch`` 必须是仓库真实分支名。CNB 仓库默认分支是 ``main``，
      写错成 ``master`` 会抛 ``ValueError: b'master' is not a valid branch``。
      所以这里先按请求的分支试，失败再退回 ``HEAD``（不指定分支）。
    """
    try:
        from dulwich import porcelain
    except ImportError as error:
        raise SyncError("未安装 dulwich，无法使用克隆通道") from error

    tmp_dir = Path(tempfile.mkdtemp(prefix="mcww_clone_"))
    work_tree = tmp_dir / "work"
    started = time.time()
    branch = (source.get("branch") or "").encode() or None

    # dulwich 默认往流里打印逐对象进度，几千行输出对用户毫无意义
    try:
        porcelain.clone(source["git_url"], str(work_tree), depth=1, branch=branch,
                        errstream=_QuietStream(), outstream=_QuietStream())
    except Exception as error:
        if branch is None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise SyncError(f"克隆 {source['name']} 失败：{error}") from error
        # 分支名不对时退回默认分支，避免因为上游改过分支名就整条通道失效
        logger.warning(f"{source['name']} 分支 {source['branch']} 不可用（{error}），改用默认分支")
        shutil.rmtree(work_tree, ignore_errors=True)
        try:
            porcelain.clone(source["git_url"], str(work_tree), depth=1,
                            errstream=_QuietStream(), outstream=_QuietStream())
        except Exception as fallback_error:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise SyncError(f"克隆 {source['name']} 失败：{fallback_error}") from fallback_error

    if not work_tree.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise SyncError(f"克隆 {source['name']} 后没有工作树")

    logger.info(f"克隆 {source['name']} 完成，用时 {time.time() - started:.1f}s")
    return work_tree, tmp_dir


def _read_upstream_version(root: Path) -> str:
    """从上游 config.py 读 version，失败返回空串。"""
    for name in ("config.py", "upstream_config.py"):
        config_path = root / name
        if not config_path.exists():
            continue
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("version"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip("\"'")
    return ""


# ---------------------------------------------------------------- 应用同步


def _copy_tree(source: Path, target: Path) -> None:
    """整体替换目标路径。"""
    if not source.exists():
        return
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _snapshot_protected(app_dir: Path) -> dict:
    """记录受保护文件的指纹，用于同步后校验。"""
    snapshot = {}
    for rel in PROTECTED_PATHS:
        path = app_dir / rel
        if path.exists():
            snapshot[rel] = _md5(path)
    return snapshot


def _verify_protected(app_dir: Path, snapshot: dict) -> list:
    """返回被意外修改或丢失的受保护文件列表。"""
    changed = []
    for rel, expected in snapshot.items():
        path = app_dir / rel
        if not path.exists() or _md5(path) != expected:
            changed.append(rel)
    return changed


def _backup(app_dir: Path, relative_paths: list) -> Path:
    """同步前备份将被替换的内容，出错时能回滚。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = app_dir / BACKUP_DIR / stamp
    for rel in relative_paths:
        source = app_dir / rel
        if not source.exists():
            continue
        target = backup_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return backup_root


def _prune_backups(app_dir: Path, keep: int = None) -> list:
    """只保留最近几次备份，删掉更早的。

    每份备份是整份 ``src``/``ok``/``assets`` 的副本（约 46MB），
    不清理的话同步十几次就白占几百 MB。按目录名（时间戳）排序，
    名字格式固定为 ``YYYYmmdd-HHMMSS``，字典序即时间序。
    """
    root = Path(app_dir) / BACKUP_DIR
    if not root.is_dir():
        return []
    keep = BACKUP_KEEP if keep is None else max(1, keep)
    snapshots = sorted((item for item in root.iterdir() if item.is_dir()), key=lambda p: p.name)
    removed = []
    for item in snapshots[:-keep] if len(snapshots) > keep else []:
        shutil.rmtree(item, ignore_errors=True)
        removed.append(item.name)
    if removed:
        logger.info(f"清理旧备份 {len(removed)} 份：{', '.join(removed)}")
    return removed


class SyncEngine:
    """执行一次上游同步。方法全部阻塞，调用方负责放到后台线程。"""

    def __init__(self, app_dir: Path):
        self.app_dir = Path(app_dir).resolve()

    # ------------------------------------------------------------ 版本检查

    def check_upstream(self, timeout: int = 60) -> dict:
        """只读上游版本号，不下载代码。"""
        errors = []
        for source in SYNC_SOURCES:
            try:
                version = self._fetch_version(source, timeout)
                local = load_state(self.app_dir).get("upstream_version", "")
                return {
                    "ok": True,
                    "source": source["name"],
                    "version": version,
                    "local_version": local,
                    "updated": bool(version) and version != local,
                    "url": source["git_url"],
                }
            except Exception as error:
                errors.append(f"{source['name']}: {error}")
                logger.warning(f"检查上游 {source['name']} 失败: {error}")
        return {"ok": False, "error": "；".join(errors)}

    def _fetch_version(self, source: dict, timeout: int) -> str:
        """用最小请求读上游 config.py 的 version，比整仓下载快得多。"""
        raw_url = self._raw_config_url(source)
        with _http_get(raw_url, timeout) as response:
            text = response.read().decode("utf-8", errors="ignore")
        # 有的镜像站对不存在的 raw 路径会返回一整个 HTML 页面而不是 404。
        # 不做这层过滤的话，报错会变成"未找到 version"，让人误以为是上游改了 config.py。
        head = text.lstrip()[:200].lower()
        if head.startswith("<!doctype") or head.startswith("<html"):
            raise SyncError(f"{source['name']} 的单文件接口返回了网页而不是源码，URL 可能已失效")
        for line in text.splitlines():
            if line.startswith("version"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip("\"'")
        raise SyncError("未在上游 config.py 中找到 version")

    @staticmethod
    def _raw_config_url(source: dict) -> str:
        if source.get("raw"):
            return source["raw"]
        git_url = source["git_url"]
        if git_url.endswith(".git"):
            git_url = git_url[:-4]
        branch = source["branch"]
        if "github.com" in git_url:
            repo = git_url.replace("https://github.com/", "")
            return f"https://raw.githubusercontent.com/{repo}/{branch}/config.py"
        if "cnb.cool" in git_url:
            # CNB 的单文件接口必须是 /-/git/raw/ 这一段。
            # /-/raw/ 会返回整页 HTML（Page not found），正则读不到 version，
            # 结果是"国内通道看起来可用、实际每次都要降级回 GitHub"。
            repo = git_url.replace("https://cnb.cool/", "")
            return f"https://cnb.cool/{repo}/-/git/raw/{branch}/config.py"
        raise SyncError(f"上游 {git_url} 没有可用的单文件接口")

    # ------------------------------------------------------------ 执行同步

    def sync(self, source: dict = None, timeout: int = 240) -> dict:
        """下载并应用上游更新。多通道依次降级。"""
        sources = [source] if source else SYNC_SOURCES
        errors = []
        for candidate in sources:
            try:
                return self._sync_from(candidate, timeout)
            except Exception as error:
                errors.append(f"{candidate['name']}: {error}")
                logger.warning(f"同步通道 {candidate['name']} 失败: {error}")
        raise SyncError("全部同步通道均失败：" + "；".join(errors))

    def _fetch_upstream_tree(self, source: dict, timeout: int) -> tuple:
        """返回 ``(上游工作树根目录, 临时目录)``，用完由调用方清理临时目录。"""
        if source.get("tarball"):
            archive = _download_tarball(source["tarball"], timeout=timeout)
            return _extract_tarball(archive), archive.parent
        return _clone_shallow(source, timeout)

    def _sync_from(self, source: dict, timeout: int) -> dict:
        # 1) 记录受保护文件指纹（要最先做，任何后续步骤失败都用它判断污染）
        protected_snapshot = _snapshot_protected(self.app_dir)

        # 2) 备份将被替换的内容
        backup_paths = list(SYNC_PATHS) + list(SYNC_FILE_MAP.values())
        backup_root = _backup(self.app_dir, backup_paths)

        # 3) 取上游工作树
        upstream_root, temp_root = self._fetch_upstream_tree(source, timeout)
        upstream_version = _read_upstream_version(upstream_root)

        changed_paths = []
        try:
            # 4) 逐路径替换（内容相同则跳过，避免无谓写盘）
            for rel in SYNC_PATHS:
                source_path = upstream_root / rel
                if not source_path.exists():
                    continue
                target = self.app_dir / rel
                if target.exists() and _md5(target) == _md5(source_path):
                    continue
                _copy_tree(source_path, target)
                changed_paths.append(rel)

            # 5) 需要改名的文件
            for upstream_name, local_name in SYNC_FILE_MAP.items():
                source_path = upstream_root / upstream_name
                if not source_path.exists():
                    continue
                target = self.app_dir / local_name
                if target.exists() and _md5(target) == _md5(source_path):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target)
                changed_paths.append(local_name)

            # 6) 只同步 icons 下的任务图标，品牌图标不动
            upstream_icons = upstream_root / "icons"
            local_icons = self.app_dir / "icons"
            if upstream_icons.exists():
                local_icons.mkdir(parents=True, exist_ok=True)
                for item in upstream_icons.iterdir():
                    if item.name in BRAND_ICONS:
                        continue
                    target = local_icons / item.name
                    if target.exists() and _md5(target) == _md5(item):
                        continue
                    _copy_tree(item, target)
                    changed_paths.append(f"icons/{item.name}")
        except Exception:
            self._rollback(backup_root)
            raise
        finally:
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

        # 7) 校验受保护文件未被污染
        touched = _verify_protected(self.app_dir, protected_snapshot)
        if touched:
            self._rollback(backup_root)
            raise SyncError(
                f"同步会改动 MC-WW 自有文件 {touched}，已回滚。"
                "请检查上游是否新增了同名路径。"
            )

        # 8) 记录状态
        state = load_state(self.app_dir)
        state["upstream_version"] = upstream_version
        state["synced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["source"] = source["name"]
        state["history"].append({
            "version": upstream_version,
            "at": state["synced_at"],
            "source": source["name"],
            "paths": changed_paths,
        })
        state["history"] = state["history"][-20:]
        save_state(self.app_dir, state)

        # 9) 本次没有实际改动就别留这份 46MB 备份（"已是最新"点一次同步也会建一份）
        if not changed_paths and backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)

        # 10) 清理旧备份：本次成功后才删，失败回滚时还要用它
        pruned = _prune_backups(self.app_dir)

        return {
            "ok": True,
            "version": upstream_version,
            "source": source["name"],
            "changed_paths": changed_paths,
            "backup": str(backup_root) if changed_paths else "",
            "pruned_backups": pruned,
            "protected_ok": True,
        }

    def _rollback(self, backup_root: Path) -> None:
        """把被替换的路径恢复到同步前的样子。"""
        logger.warning(f"同步失败，从 {backup_root} 回滚")
        if not backup_root.exists():
            return
        for rel in list(SYNC_PATHS) + list(SYNC_FILE_MAP.values()):
            source = backup_root / rel
            if not source.exists():
                continue
            _copy_tree(source, self.app_dir / rel)


# ---------------------------------------------------------------- 便捷接口


def run_sync_async(app_dir: Path, on_done=None, source: dict = None):
    """在后台线程执行同步，完成后回调 ``on_done(result)``（失败也回调）。"""

    def worker():
        engine = SyncEngine(app_dir)
        try:
            result = engine.sync(source=source)
        except Exception as error:
            logger.error(f"同步失败: {error}")
            result = {"ok": False, "error": str(error)}
        if on_done:
            on_done(result)

    thread = threading.Thread(target=worker, daemon=True, name="MCWW-Sync")
    thread.start()
    return thread
