from fastapi import FastAPI
import subprocess
import logging
import os
import time
import re
import shutil
import multiprocessing
import threading
import enum
from ftplib import FTP_TLS, error_perm, error_temp

# ==================== 日志配置 ====================
LOG_PATH = r"D:\auto_test_api\trigger_run.log"
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger("test-trigger-service")

# ==================== 路径常量 ====================
# 以当前脚本所在目录为基准，定位 Release 目录下的 CLI 与用例文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLI_EXE_PATH = os.path.join(BASE_DIR, "Release", "AutoTestCopilot.CLI.exe")
CASES_XLSX_PATH = os.path.join(BASE_DIR, "Release", "Resources", "a.xlsx")

# CMGE Copilot 本地安装路径（安装后验证用）
COPILOT_INSTALL_DIR = r"C:\CMGE Copilot"
COPILOT_API_EXE = os.path.join(COPILOT_INSTALL_DIR, "API", "CMGECopilot.API.exe")
COPILOT_UI_EXE = os.path.join(COPILOT_INSTALL_DIR, "UI", "CMGECopilot.UI.exe")

# 本地版本信息存储目录与文件
COPILOT_STORE_DIR = r"D:\CMGE Copilot Store"
LATEST_VERSION_FILE = os.path.join(COPILOT_STORE_DIR, "latest Version.txt")
COPILOT_TEMP_DIR = os.path.join(COPILOT_STORE_DIR, "temp")

# CLI 默认执行超时时间（秒），30 分钟
DEFAULT_TIMEOUT_SECONDS = 30 * 60

# ==================== FTP 连接配置 ====================
FTP_HOST = "devftp01.cmit.local"
FTP_PORT = 9023
FTP_USER = "wangxf@cmgos.com"
FTP_CRED_SERVICE = "CMGE_FTP"  # Windows 凭据管理器中的服务名
FTP_REMOTE_BASE_DIR = "/dev-release/CMGE_Copilot/CMGE COPILOT"

# ==================== 执行阶段（用于互斥锁状态提示） ====================
class ExecutionStage(enum.Enum):
    IDLE = "idle"
    FTP_CHECKING = "ftp_checking"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    TESTING = "testing"

_current_stage = ExecutionStage.IDLE
# 执行互斥锁，保证同一时间只处理一个请求
_execution_lock = threading.Lock()


# ==================== 辅助函数 ====================
def _decode_cli_output(raw: bytes | None) -> str:
    """尝试多种编码解码 CLI 输出，优先 UTF-8，回退 GBK，最终容错替换"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _get_ftp_password() -> str:
    """从 Windows 凭据管理器获取 FTP 密码"""
    import keyring
    password = keyring.get_password(FTP_CRED_SERVICE, FTP_USER)
    if not password:
        raise RuntimeError(
            f"无法从凭据管理器获取 FTP 密码。"
            f"请先执行: python -c \"import keyring; keyring.set_password('{FTP_CRED_SERVICE}', '{FTP_USER}', '你的密码')\""
        )
    return password


def _parse_version(folder_name: str) -> tuple:
    """
    解析文件夹名中的版本信息，返回 (日期, 序号) 用于排序。
    文件夹名格式示例: 487_ForBuild_CMGE Service AI Agent-CI_20260224
    """
    date_match = re.search(r'(\d{8})$', folder_name.strip())
    seq_match = re.search(r'^(\d+)', folder_name.strip())
    date_val = int(date_match.group(1)) if date_match else 0
    seq_val = int(seq_match.group(1)) if seq_match else 0
    return (date_val, seq_val)


def _is_valid_version_folder(folder_name: str) -> bool:
    """判断文件夹名是否为有效的版本文件夹（必须包含日期后缀）"""
    return bool(re.search(r'\d{8}$', folder_name.strip())) and bool(re.search(r'^\d+', folder_name.strip()))


def _read_local_version() -> str | None:
    """读取本地已安装版本号，文件不存在时返回 None（视为首次安装）"""
    if not os.path.exists(LATEST_VERSION_FILE):
        return None
    try:
        with open(LATEST_VERSION_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content if content else None
    except Exception as e:
        logger.warning(f"读取本地版本文件失败: {e}")
        return None


def _write_local_version(version_name: str) -> bool:
    """写入最新版本号到本地版本文件"""
    try:
        os.makedirs(COPILOT_STORE_DIR, exist_ok=True)
        with open(LATEST_VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(version_name)
        logger.info(f"本地版本文件已更新为: {version_name}")
        return True
    except Exception as e:
        logger.warning(f"写入本地版本文件失败: {e}，不影响主流程继续")
        return False


def _cleanup_temp_dir():
    """清理临时下载目录"""
    try:
        if os.path.exists(COPILOT_TEMP_DIR):
            shutil.rmtree(COPILOT_TEMP_DIR)
            logger.info(f"临时目录已清理: {COPILOT_TEMP_DIR}")
    except Exception as e:
        logger.warning(f"清理临时目录失败: {e}")


def _ftp_connect():
    """建立 FTPS（显式 TLS）连接并返回 ftp 对象"""
    global _current_stage
    _current_stage = ExecutionStage.FTP_CHECKING

    password = _get_ftp_password()
    ftp = FTP_TLS()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
    ftp.login(FTP_USER, password)
    ftp.prot_p()  # 将数据连接也升级为 TLS 加密
    logger.info(f"FTPS 连接成功: {FTP_HOST}:{FTP_PORT}")
    return ftp


def _ftp_get_latest_version(ftp) -> str:
    """
    连接 FTP，列出远程目录，解析并返回最新版本文件夹名。
    返回值: 最新版本文件夹名字符串，如 "487_ForBuild_CMGE Service AI Agent-CI_20260224"
    """
    # 切换到目标目录并列出内容
    ftp.cwd(FTP_REMOTE_BASE_DIR)
    items = ftp.nlst()
    logger.info(f"FTP 目录 {FTP_REMOTE_BASE_DIR} 下共有 {len(items)} 项")

    # 过滤出有效的版本文件夹
    version_folders = [item for item in items if _is_valid_version_folder(item)]
    if not version_folders:
        raise RuntimeError(
            f"FTP 目录 {FTP_REMOTE_BASE_DIR} 下没有找到有效的版本文件夹。"
            f"现有项: {items}"
        )

    # 按版本排序：日期降序优先，同日期按序号降序
    version_folders.sort(key=_parse_version, reverse=True)
    latest = version_folders[0]
    logger.info(f"FTP 最新版本文件夹: {latest}（共 {len(version_folders)} 个版本文件夹）")
    return latest


def _ftp_download_version(ftp, version_folder_name: str) -> str:
    """
    从 FTP 下载指定版本文件夹内的所有文件到本地临时目录。
    返回值: 本地下载目录路径
    """
    global _current_stage
    _current_stage = ExecutionStage.DOWNLOADING

    remote_dir = f"{FTP_REMOTE_BASE_DIR}/{version_folder_name}"
    local_dir = os.path.join(COPILOT_TEMP_DIR, version_folder_name)
    os.makedirs(local_dir, exist_ok=True)

    ftp.cwd(remote_dir)
    files = ftp.nlst()
    logger.info(f"开始下载版本 {version_folder_name}，共 {len(files)} 个文件")

    for filename in files:
        local_path = os.path.join(local_dir, filename)
        logger.info(f"正在下载: {filename}")
        with open(local_path, "wb") as f:
            ftp.retrbinary(f"RETR {filename}", f.write)
        logger.info(f"下载完成: {filename} → {local_path}")

    logger.info(f"版本 {version_folder_name} 全部文件下载完成，本地路径: {local_dir}")
    return local_dir


def _silent_install(local_version_dir: str) -> int:
    """
    在本地下载目录中执行静默安装。
    使用 CMGECopilot-Setup.msi /q 进行静默安装。
    返回值: subprocess 的 returncode
    """
    global _current_stage
    _current_stage = ExecutionStage.INSTALLING

    msi_path = os.path.join(local_version_dir, "CMGECopilot-Setup.msi")
    if not os.path.exists(msi_path):
        raise FileNotFoundError(f"安装包不存在: {msi_path}")

    logger.info(f"开始静默安装: {msi_path}")
    result = subprocess.run(
        ["msiexec", "/i", msi_path, "/q"],
        capture_output=True,
        timeout=600  # 安装超时 10 分钟
    )
    stdout_text = _decode_cli_output(result.stdout)
    stderr_text = _decode_cli_output(result.stderr)
    logger.info(f"MSI 安装完成，退出码: {result.returncode}, stdout: {stdout_text}, stderr: {stderr_text}")
    return result.returncode


def _verify_installation() -> bool:
    """验证 CMGE Copilot 安装后，API 和 UI 可执行文件是否存在"""
    api_ok = os.path.exists(COPILOT_API_EXE)
    ui_ok = os.path.exists(COPILOT_UI_EXE)
    logger.info(
        f"安装验证 - API({COPILOT_API_EXE}): {'存在' if api_ok else '不存在'}, "
        f"UI({COPILOT_UI_EXE}): {'存在' if ui_ok else '不存在'}"
    )
    return api_ok and ui_ok


def _check_and_update_copilot(task_info: dict) -> dict:
    """
    完整的 FTP 版本检查与更新流程。
    返回值: dict，code=0 表示有更新且安装成功（继续执行测试），
            code=1 表示版本相同（不执行测试），
            code<0 表示出错（终止流程）。
    """
    ftp = None
    try:
        # 1. 连接 FTP
        ftp = _ftp_connect()

        # 2. 获取 FTP 最新版本
        ftp_latest = _ftp_get_latest_version(ftp)

        # 3. 读取本地版本
        local_version = _read_local_version()
        is_first_install = local_version is None
        logger.info(
            f"版本比较 - FTP最新: {ftp_latest}, 本地: {'无（首次安装）' if is_first_install else local_version}"
        )

        # 4. 比较版本
        if not is_first_install and local_version == ftp_latest:
            logger.info("当前版本已是最新，无需更新")
            return {
                "code": 1,
                "msg": "当前版本已是最新，无需更新，未执行测试",
                "current_version": local_version,
                "ftp_latest_version": ftp_latest,
            }

        # 5. 下载版本文件夹
        local_version_dir = _ftp_download_version(ftp, ftp_latest)

        # 关闭 FTP 连接（下载完成后不再需要）
        try:
            ftp.quit()
        except Exception:
            pass
        ftp = None

        # 6. 静默安装
        msi_returncode = _silent_install(local_version_dir)
        if msi_returncode != 0:
            raise RuntimeError(
                f"MSI 静默安装失败，退出码: {msi_returncode}"
            )

        # 7. 安装后验证
        if not _verify_installation():
            raise RuntimeError(
                f"安装后验证失败：预期文件不存在。"
                f"API: {COPILOT_API_EXE}（存在: {os.path.exists(COPILOT_API_EXE)}），"
                f"UI: {COPILOT_UI_EXE}（存在: {os.path.exists(COPILOT_UI_EXE)}）"
            )

        # 8. 更新本地版本文件
        _write_local_version(ftp_latest)

        # 9. 清理临时文件
        _cleanup_temp_dir()

        logger.info(f"CMGE Copilot 已成功更新安装至版本: {ftp_latest}")
        return {
            "code": 0,
            "msg": f"CMGE Copilot 已成功更新安装至版本: {ftp_latest}" if is_first_install else f"CMGE Copilot 已成功从 {local_version} 更新至 {ftp_latest}",
            "previous_version": None if is_first_install else local_version,
            "installed_version": ftp_latest,
        }

    except Exception as e:
        logger.error(f"FTP 版本检查/更新过程中出错: {e}", exc_info=True)
        # 尝试关闭 FTP 连接
        if ftp:
            try:
                ftp.quit()
            except Exception:
                pass
        # 清理临时文件（安装失败时保留以便排查）
        return {
            "code": -20,
            "msg": f"FTP 更新流程失败: {str(e)}",
            "error_detail": str(e),
        }
    finally:
        global _current_stage
        _current_stage = ExecutionStage.IDLE


# ==================== FastAPI 应用 ====================
app = FastAPI(title="自动化测试触发监听服务", version="2.0")


@app.post("/api/trigger/auto-test")
def trigger_test(task_info: dict):
    """
    接收远程触发请求，执行以下流程：
    1. （默认）检查 FTP 版本，有更新则下载安装
    2. 前置校验 CLI 和用例文件
    3. 执行 AutoTestCopilot.CLI 测试

    请求体参数：
    - timeout: CLI 执行超时时间（秒），默认 1800
    - skip_update: true 时跳过 FTP 检查，直接执行测试
    """
    global _current_stage

    logger.info(f"收到远程触发请求，入参数据：{task_info}")

    # ========== 互斥控制：同一时间只允许处理一个请求 ==========
    if not _execution_lock.acquire(blocking=False):
        # 根据当前执行阶段返回不同的提示
        stage_messages = {
            ExecutionStage.FTP_CHECKING: ("当前正在检查FTP版本信息，请稍后再试", -10),
            ExecutionStage.DOWNLOADING: ("当前正在从FTP下载新版本，请稍后再试", -12),
            ExecutionStage.INSTALLING: ("当前正在静默安装CMGE Copilot新版本，请稍后再试", -13),
            ExecutionStage.TESTING: ("当前已有测试任务正在执行，请稍后再试", -10),
        }
        msg, code = stage_messages.get(
            _current_stage,
            ("当前系统忙碌，请稍后再试", -10)
        )
        logger.warning(f"请求被拒绝（阶段: {_current_stage.value}）：{msg}，入参：{task_info}")
        return {
            "code": code,
            "msg": msg,
            "task_info": task_info,
            "stdout": "",
            "stderr": msg,
            "exit_code": -99,
        }
    # ========================================================

    try:
        # ========== 解析参数 ==========
        timeout = (task_info.get("timeout", DEFAULT_TIMEOUT_SECONDS)
                   if isinstance(task_info, dict) else DEFAULT_TIMEOUT_SECONDS)
        skip_update = (task_info.get("skip_update", False)
                      if isinstance(task_info, dict) else False)

        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            err_msg = f"超时参数timeout无效：{timeout}，必须为正数（单位：秒）"
            logger.error(err_msg)
            return {
                "code": -1,
                "msg": f"执行失败：{err_msg}",
                "task_info": task_info,
                "stdout": "",
                "stderr": err_msg,
                "exit_code": -99,
            }
        # ================================

        # ========== FTP 版本检查与更新（可通过 skip_update 跳过） ==========
        if not skip_update:
            update_result = _check_and_update_copilot(task_info)
            if update_result["code"] == 1:
                # 版本相同，不执行测试
                return {
                    "code": 1,
                    "msg": update_result["msg"],
                    "task_info": task_info,
                    "current_version": update_result.get("current_version", ""),
                    "ftp_latest_version": update_result.get("ftp_latest_version", ""),
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                }
            elif update_result["code"] != 0:
                # FTP 流程出错，终止
                return {
                    "code": update_result["code"],
                    "msg": update_result["msg"],
                    "task_info": task_info,
                    "error_detail": update_result.get("error_detail", ""),
                    "stdout": "",
                    "stderr": update_result["msg"],
                    "exit_code": -99,
                }
            # code == 0: 更新成功，继续执行测试
            logger.info(f"FTP 更新完成，继续执行测试: {update_result['msg']}")
        else:
            logger.info("已跳过 FTP 版本检查（skip_update=true），直接执行测试")
        # ========================================================

        # ========== 前置校验：检查CLI可执行文件 ==========
        if not os.path.exists(CLI_EXE_PATH):
            err_msg = f"CLI可执行文件不存在，路径：{CLI_EXE_PATH}"
            logger.error(err_msg)
            return {
                "code": -1,
                "msg": "执行失败：CLI可执行文件不存在",
                "task_info": task_info,
                "stdout": "",
                "stderr": err_msg,
                "exit_code": -99,
            }

        if not os.access(CLI_EXE_PATH, os.R_OK):
            err_msg = f"CLI可执行文件无读取权限，路径：{CLI_EXE_PATH}"
            logger.error(err_msg)
            return {
                "code": -2,
                "msg": "执行失败：CLI可执行文件不可读/无执行权限",
                "task_info": task_info,
                "stdout": "",
                "stderr": err_msg,
                "exit_code": -99,
            }
        # ==============================================

        # ========== 前置校验：检查用例Excel文件 ==========
        if not os.path.exists(CASES_XLSX_PATH):
            err_msg = f"用例Excel文件不存在，路径：{CASES_XLSX_PATH}"
            logger.error(err_msg)
            return {
                "code": -1,
                "msg": "执行失败：用例Excel文件不存在",
                "task_info": task_info,
                "stdout": "",
                "stderr": err_msg,
                "exit_code": -99,
            }
        # ==============================================

        # ========== 执行 CLI 测试 ==========
        _current_stage = ExecutionStage.TESTING
        cmd = [
            CLI_EXE_PATH,
            "--cases", CASES_XLSX_PATH
        ]
        logger.info(f"开始执行CLI，超时设置：{timeout}秒，命令：{' '.join(cmd)}")
        try:
            run_result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired as e:
            out = _decode_cli_output(e.stdout)
            err = _decode_cli_output(e.stderr)
            err_msg = f"CLI执行超时，已超过{timeout}秒被强制终止"
            logger.error(f"{err_msg}\n已捕获输出：stdout={out}\nstderr={err}")
            return {
                "code": -11,
                "msg": err_msg,
                "task_info": task_info,
                "stdout": out,
                "stderr": err,
                "exit_code": -99,
            }
        stdout_text = _decode_cli_output(run_result.stdout)
        stderr_text = _decode_cli_output(run_result.stderr)
        log_text = f"CLI执行完成，退出码：{run_result.returncode}\n标准输出：{stdout_text}\n错误输出：{stderr_text}"
        logger.info(log_text)
        return {
            "code": 200 if run_result.returncode == 0 else -3,
            "msg": "AutoTestCopilot.CLI执行完毕" if run_result.returncode == 0 else "AutoTestCopilot.CLI执行报错",
            "task_info": task_info,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "exit_code": run_result.returncode,
        }

    finally:
        _current_stage = ExecutionStage.IDLE
        _execution_lock.release()


# ==================== 子进程启动 uvicorn 服务 ====================
def run_uvicorn_server():
    import uvicorn
    uvicorn.run(
        app="test_trigger:app",
        host="0.0.0.0",
        port=8090,
        log_level="info"
    )

if __name__ == "__main__":
    logger.info("自动化监听服务主程序启动（v2.0 - 含FTP自动更新）")
    # 启动uvicorn子进程
    server_process = multiprocessing.Process(target=run_uvicorn_server, daemon=True)
    server_process.start()
    logger.info(f"uvicorn监听子进程已启动，PID={server_process.pid}")
    # 主线程无限循环阻塞，防止程序退出，10秒检测一次进程状态
    while True:
        if not server_process.is_alive():
            logger.error("uvicorn监听进程意外退出，自动重启")
            server_process = multiprocessing.Process(target=run_uvicorn_server, daemon=True)
            server_process.start()
            logger.info(f"uvicorn重启完成，新PID={server_process.pid}")
        time.sleep(10)
