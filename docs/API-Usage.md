# 自动化测试触发服务 API 使用说明

## 1. 服务概述

自动化测试触发监听服务（Test Trigger Service）是一个基于 FastAPI 的 HTTP 服务，用于接收远程触发请求，在本地 Windows 机器上执行 `AutoTestCopilot.CLI.exe` 自动化测试程序。

- **服务名称**：自动化测试触发监听服务
- **版本**：1.0
- **监听端口**：8090
- **服务地址**：`http://<服务器IP>:8090`

## 2. 启动服务

### 方式一：直接运行脚本

```bash
python test_trigger.py
```

脚本启动后会以子进程方式运行 uvicorn 服务器，主线程每 10 秒检测一次子进程状态，若意外退出则自动重启。

### 方式二：使用 uvicorn 直接启动

```bash
uvicorn test_trigger:app --host 0.0.0.0 --port 8090 --log-level info
```

## 3. 目录结构

```
Local_TestMachine_API/
├── test_trigger.py          # 主程序（FastAPI 服务）
├── Release/
│   ├── AutoTestCopilot.CLI.exe   # CLI 可执行程序
│   └── Resources/
│       └── a.xlsx                 # 测试用例文件
└── docs/
    ├── API-Usage.md               # 本文档
    └── AutoTestCopilot.CLI-Usage.md  # CLI 使用说明
```

## 4. API 接口

### 4.1 触发自动化测试

触发本地 AutoTestCopilot.CLI.exe 执行自动化测试。

**接口地址**：`POST /api/trigger/auto-test`

**请求头**：
```
Content-Type: application/json
```

**请求体**：

请求体为任意 JSON 对象（`task_info`），用于传递任务相关信息。该信息会原样记录到日志中，并在响应中回传。其中包含一个可选的控制字段 `timeout`（详见下文）。

| 字段 | 类型 | 是否必填 | 说明 |
|------|------|----------|------|
| `timeout` | number | 否 | CLI 执行超时时间，单位：秒。不传时默认 1800（30 分钟）。必须为正数。 |
| 其他自定义字段 | any | 否 | 如 `task_id`、`remark` 等，原样记录到日志并回传，服务不解析。 |

示例：
```json
{
  "task_id": "T20260717001",
  "trigger_from": "linux-build-server",
  "build_no": "B12345",
  "remark": "每日构建回归测试",
  "timeout": 3600
}
```

> 说明：`timeout` 仅控制 CLI 进程的执行时长。超时后服务会强制终止子进程并返回 `code: -11`。

**响应格式**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码，详见下文 |
| `msg` | string | 结果描述 |
| `task_info` | object | 原样返回的请求体内容 |
| `stdout` | string | CLI 程序标准输出 |
| `stderr` | string | CLI 程序错误输出 |
| `exit_code` | int | CLI 进程退出码 |

**业务状态码（code）**：

| code | 说明 |
|------|------|
| `200` | CLI 执行成功（退出码为 0） |
| `-1` | 前置文件不存在（CLI 或用例 Excel），或 `timeout` 参数无效 |
| `-2` | CLI 可执行文件无读取/执行权限 |
| `-3` | CLI 执行失败（退出码非 0） |
| `-10` | 当前已有测试任务正在执行，请求被拒绝（互斥控制） |
| `-11` | CLI 执行超时，已被强制终止 |
| `-99` | 前置校验失败/超时/互斥拒绝时的占位退出码 |

**CLI 退出码（exit_code）**：

当 `code = -3` 时，可通过 `exit_code` 进一步判断失败原因：

| exit_code | 说明 |
|-----------|------|
| `0` | 执行完成（成功） |
| `1` | 命令行参数解析失败 |
| `2` | 用例文件不存在，或读取/校验后没有可执行用例 |
| `3` | 初始化失败，运行环境未就绪 |
| `5` | 执行过程中出现未处理异常 |

## 5. 调用示例

### curl 示例

```bash
curl -X POST http://127.0.0.1:8090/api/trigger/auto-test \
  -H "Content-Type: application/json" \
  -d '{"task_id":"T001","remark":"触发测试"}'
```

### PowerShell 示例

```powershell
$body = @{
    task_id = "T001"
    remark  = "触发测试"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8090/api/trigger/auto-test" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

### Python 示例

```python
import requests

url = "http://127.0.0.1:8090/api/trigger/auto-test"
data = {"task_id": "T001", "remark": "触发测试"}

response = requests.post(url, json=data)
result = response.json()
print(result)
```

### 成功响应示例

```json
{
  "code": 200,
  "msg": "AutoTestCopilot.CLI执行完毕",
  "task_info": {
    "task_id": "T001",
    "remark": "触发测试"
  },
  "stdout": "Cases: ...\n用例执行完成...",
  "stderr": "",
  "exit_code": 0
}
```

### 失败响应示例（CLI 不存在）

```json
{
  "code": -1,
  "msg": "执行失败：CLI可执行文件不存在",
  "task_info": {
    "task_id": "T001"
  },
  "stdout": "",
  "stderr": "CLI可执行文件不存在，路径：C:\\...\\Release\\AutoTestCopilot.CLI.exe",
  "exit_code": -99
}
```

## 6. 运行前提

在使用本服务前，请确保目标机器满足以下条件：

1. **Python 环境**：已安装 Python 3.x，包含 `fastapi`、`uvicorn` 依赖
2. **.NET Framework 4.8**：AutoTestCopilot.CLI.exe 的运行依赖
3. **外部程序**：以下路径的程序存在且可运行
   - `C:\CMGE Copilot\API\CMGECopilot.API.exe`
   - `C:\CMGE Copilot\UI\CMGECopilot.UI.exe`
4. **UI 窗口**：窗口标题包含 `CMGE Copilot`
5. **用例文件**：`Release\Resources\a.xlsx` 存在且格式正确
6. **OCR 依赖（可选）**：`C:\Program Files\Tesseract-OCR\tesseract.exe`

## 7. 日志

### 服务日志

- **路径**：`D:\auto_test_api\trigger_run.log`
- **格式**：`时间 | 级别 | 消息`
- **记录内容**：
  - 服务启动/重启
  - 收到的触发请求及入参
  - CLI 执行结果（退出码、标准输出、错误输出）
  - 前置校验失败信息

### CLI 运行日志

CLI 自身的运行日志位于：
```
%LocalAppData%\AutoTestCopilot\logs
```

典型文件名：`AutoTestCopilot.CLI_yyyyMMdd_HHmmss.log`

## 8. 注意事项

1. **同步阻塞**：接口为同步调用，会等待 CLI 执行完成后再返回。测试用例较多时响应时间可能较长，调用方需设置合理的超时时间。
2. **单实例执行（互斥控制）**：服务内置互斥锁，同一时间只允许处理一个请求。若上一个任务尚未结束，新请求会立即返回 `code: -10`（当前已有测试任务正在执行），不会排队等待。调用方收到该错误后应稍后重试。
3. **超时控制**：CLI 默认超时 30 分钟（1800 秒）。可在请求体的 `timeout` 字段中传入自定义秒数覆盖默认值。超时后子进程被强制终止并返回 `code: -11`，同时会回传超时前已捕获的 stdout/stderr。
4. **桌面会话**：CLI 依赖当前桌面会话进行 UI 自动化操作，请确保服务在有桌面会话的用户环境下运行，不要以 Windows 服务方式运行。
5. **相对路径**：CLI 可执行文件和用例文件均以 `test_trigger.py` 所在目录为基准进行相对路径定位，移动脚本时请保持 `Release` 目录的相对位置不变。
6. **防火墙**：服务监听 `0.0.0.0:8090`，请确保防火墙已开放 8090 端口。
