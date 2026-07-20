from fastapi import FastAPI
import subprocess
import logging
import os
import time
import multiprocessing
import threading
# 日志文件路径
LOG_PATH = r"D:\auto_test_api\trigger_run.log"
# 以当前脚本所在目录为基准，定位 Release 目录下的 CLI 与用例文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLI_EXE_PATH = os.path.join(BASE_DIR, "Release", "AutoTestCopilot.CLI.exe")
CASES_XLSX_PATH = os.path.join(BASE_DIR, "Release", "Resources", "a.xlsx")
# CLI 默认执行超时时间（秒），30 分钟
DEFAULT_TIMEOUT_SECONDS = 30 * 60
# 执行互斥锁，保证同一时间只处理一个请求
_execution_lock = threading.Lock()


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
# 日志配置
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger("test-trigger-service")
app = FastAPI(title="自动化测试触发监听服务", version="1.0")

@app.post("/api/trigger/auto-test")
def trigger_test(task_info: dict):
    """接收Linux API推送，执行本地AutoTestCopilot.CLI测试程序"""
    logger.info(f"收到远程触发请求，入参数据：{task_info}")

    # ========== 互斥控制：同一时间只允许处理一个请求 ==========
    if not _execution_lock.acquire(blocking=False):
        err_msg = "当前已有测试任务正在执行，请稍后再试"
        logger.warning(f"请求被拒绝：{err_msg}，入参：{task_info}")
        return {
            "code": -10,
            "msg": err_msg,
            "task_info": task_info,
            "stdout": "",
            "stderr": err_msg,
            "exit_code": -99
        }
    # ========================================================

    try:
        # ========== 解析超时参数 ==========
        # 支持在 task_info 中传入 "timeout"（单位：秒）覆盖默认值
        timeout = task_info.get("timeout", DEFAULT_TIMEOUT_SECONDS) if isinstance(task_info, dict) else DEFAULT_TIMEOUT_SECONDS
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            err_msg = f"超时参数timeout无效：{timeout}，必须为正数（单位：秒）"
            logger.error(err_msg)
            return {
                "code": -1,
                "msg": f"执行失败：{err_msg}",
                "task_info": task_info,
                "stdout": "",
                "stderr": err_msg,
                "exit_code": -99
            }
        # ================================

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
                "exit_code": -99
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
                "exit_code": -99
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
                "exit_code": -99
            }
        # ==============================================

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
                "exit_code": -99
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
            "exit_code": run_result.returncode
        }
    finally:
        _execution_lock.release()

# 子进程单独启动uvicorn服务
def run_uvicorn_server():
    import uvicorn
    uvicorn.run(
        app="test_trigger:app",
        host="0.0.0.0",
        port=8090,
        log_level="info"
    )

if __name__ == "__main__":
    logger.info("自动化监听服务主程序启动")
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