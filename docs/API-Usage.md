# 自动化测试触发服务 API 使用说明

## 1. 服务概述

自动化测试触发监听服务（Test Trigger Service）是一个基于 FastAPI 的 HTTP 服务，用于接收远程触发请求，在本地 Windows 机器上自动检查 FTP 上的 CMGE Copilot 最新版本，如有更新则下载并静默安装，然后执行 `AutoTestCopilot.CLI.exe` 自动化测试程序。

本服务面向 **CMGE Copilot 软件的自动化测试与发布流程**：开发人员完成新版本并上传至 FTP 后，调用方（如 Linux 构建服务器）通过调用本 API 触发完整的"版本检查 → 下载安装 → 自动化测试"流程。

- **服务名称**：自动化测试触发监听服务
- **版本**：2.0
- **监听端口**：8090
- **服务地址**：`http://<服务器IP>:8090`

### 1.1 v2.0 新增能力

相比 v1.0，v2.0 新增了以下功能：

- **FTP 自动更新检查**：通过 FTPS（显式 TLS 加密）连接 FTP 服务器，检查 `/dev-release/CMGE_Copilot/CMGE COPILOT/` 目录下的最新版本
- **自动下载与静默安装**：检测到新版本后，自动下载整个版本文件夹并通过 MSI 静默安装 CMGE Copilot
- **版本记录管理**：通过 `D:\CMGE Copilot Store\latest Version.txt` 记录当前已安装版本
- **阶段感知的互斥控制**：互斥锁拒绝请求时，会返回当前所处的执行阶段（FTP 检查中/下载中/安装中/测试中）
- **跳过更新模式**：支持 `skip_update` 参数，跳过 FTP 检查直接执行测试

## 2. 启动服务

### 2.1 首次部署准备

在首次启动服务之前，请完成以下准备工作：

**（1）安装 Python 依赖**

```bash
pip install fastapi uvicorn keyring
```

> `keyring` 用于从 Windows 凭据管理器读取 FTP 密码。

**（2）配置 FTP 密码到 Windows 凭据管理器**

只需执行一次，密码会被安全存储在 Windows 凭据管理器中：

```bash
python -c "import keyring; keyring.set_password('CMGE_FTP', 'wangxf@cmgos.com', '你的实际密码')"
```

或在 Windows 凭据管理器 GUI 中手动添加：
- **Internet 或网络地址（服务名）**：`CMGE_FTP`
- **用户名**：`wangxf@cmgos.com`
- **密码**：实际 FTP 密码

> 如果未配置密码，服务启动后调用 API 将返回 `-20` 错误并提示配置密码。

**（3）确保本地存储目录存在**

```bash
mkdir "D:\CMGE Copilot Store"
```

首次运行时，如果 `D:\CMGE Copilot Store\latest Version.txt` 不存在，服务会视为首次安装，直接从 FTP 下载最新版本并安装。

### 2.2 方式一：直接运行脚本（推荐）

```bash
python test_trigger.py
```

脚本启动后会以子进程方式运行 uvicorn 服务器，主线程每 10 秒检测一次子进程状态，若意外退出则自动重启。

### 2.3 方式二：使用 uvicorn 直接启动

```bash
uvicorn test_trigger:app --host 0.0.0.0 --port 8090 --log-level info
```

> 注意：使用此方式时 uvicorn 进程退出后不会自动重启。

## 3. 目录结构

### 3.1 服务程序目录

```
Local_TestMachine_API/
├── test_trigger.py              # 主程序（FastAPI 服务，v2.0 含 FTP 自动更新）
├── Release/
│   ├── AutoTestCopilot.CLI.exe   # 自动化测试 CLI 可执行程序
│   └── Resources/
│       └── a.xlsx               # 测试用例文件
└── docs/
    ├── API-Usage.md              # 本文档
    └── AutoTestCopilot.CLI-Usage.md  # CLI 使用说明
```

### 3.2 CMGE Copilot 安装目录（被测软件）

```
C:\CMGE Copilot\
├── API\
│   └── CMGECopilot.API.exe      # CMGE Copilot 后端 API 程序
└── UI\
    └── CMGECopilot.UI.exe       # CMGE Copilot 前端 UI 程序
```

### 3.3 本地版本存储目录

```
D:\CMGE Copilot Store\
├── latest Version.txt            # 记录当前已安装的版本文件夹名
└── temp\                         # FTP 下载临时目录（安装完成后自动清理）
```

## 4. API 接口

### 4.1 触发自动化测试（含 FTP 自动更新）

**接口地址**：`POST /api/trigger/auto-test`

**功能**：

1. 获取互斥锁（防止并发）
2. 解析请求参数
3. **（默认）连接 FTP，检查 CMGE Copilot 最新版本**
   - 如有更新 → 下载整个版本文件夹 → 静默安装 → 更新版本记录
   - 如版本相同 → 返回提示，不执行测试
   - 如 FTP 连接失败 → 返回错误，终止流程
4. 前置校验 CLI 可执行文件和用例文件
5. 执行 `AutoTestCopilot.CLI.exe` 自动化测试
6. 释放互斥锁

**请求头**：
```
Content-Type: application/json
```

**请求体**：

请求体为任意 JSON 对象（`task_info`），用于传递任务相关信息。该信息会原样记录到日志中，并在响应中回传。

| 字段 | 类型 | 是否必填 | 默认值 | 说明 |
|------|------|----------|--------|------|
| `timeout` | number | 否 | `1800` | CLI 执行超时时间，单位：秒（30 分钟）。必须为正数。 |
| `skip_update` | boolean | 否 | `false` | 设为 `true` 时跳过 FTP 版本检查，直接执行测试。 |
| 其他自定义字段 | any | 否 | — | 如 `task_id`、`remark` 等，原样记录到日志并回传，服务不解析。 |

**请求示例**：

```json
{
  "task_id": "T20260717001",
  "trigger_from": "linux-build-server",
  "build_no": "B12345",
  "remark": "每日构建回归测试",
  "timeout": 3600
}
```

**跳过 FTP 检查的请求示例**：

```json
{
  "task_id": "T20260720002",
  "skip_update": true,
  "remark": "使用当前版本直接执行测试"
}
```

> 说明：
> - `timeout` 仅控制 CLI 进程的执行时长，不影响 FTP 连接/下载/安装的时间。
> - `skip_update=true` 适用于日常测试场景，无需等待 FTP 检查即可直接触发测试。

**响应格式**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码，详见下文 |
| `msg` | string | 结果描述 |
| `task_info` | object | 原样返回的请求体内容 |
| `stdout` | string | CLI 程序标准输出（仅执行 CLI 时有值） |
| `stderr` | string | CLI 程序错误输出或错误详情 |
| `exit_code` | int | CLI 进程退出码或流程占位码 |

**响应中的额外字段（特定场景）**：

| 字段 | 出现场景 | 说明 |
|------|----------|------|
| `current_version` | 版本相同（code=1） | 当前本地已安装的版本文件夹名 |
| `ftp_latest_version` | 版本相同（code=1） | FTP 上最新的版本文件夹名 |
| `previous_version` | 更新成功后执行测试 | 更新前的版本（首次安装时为 `null`） |
| `installed_version` | 更新成功后执行测试 | 刚安装的版本文件夹名 |
| `error_detail` | FTP 流程失败（code=-20） | 具体的错误详细信息 |

### 4.2 业务状态码（code）

#### 成功/正常状态

| code | 说明 |
|------|------|
| `200` | CLI 测试执行成功（退出码为 0） |
| `1` | 当前版本已是最新，无需更新，未执行测试（正常状态，非错误） |

#### 前置校验失败

| code | 说明 |
|------|------|
| `-1` | 前置文件不存在（CLI 或用例 Excel），或 `timeout` 参数无效 |
| `-2` | CLI 可执行文件无读取/执行权限 |

#### 互斥控制拒绝

| code | 说明 |
|------|------|
| `-10` | 当前已有测试任务正在执行或正在检查 FTP 版本，请求被拒绝 |
| `-12` | 当前正在从 FTP 下载新版本，请求被拒绝 |
| `-13` | 当前正在静默安装 CMGE Copilot 新版本，请求被拒绝 |

#### 执行异常

| code | 说明 |
|------|------|
| `-3` | CLI 执行失败（退出码非 0） |
| `-11` | CLI 执行超时，已被强制终止 |
| `-20` | FTP 更新流程失败（含连接失败、下载失败、安装失败、验证失败等） |

#### 占位码

| code | 说明 |
|------|------|
| `-99` | 前置校验失败/超时/互斥拒绝/FTP 失败时的占位退出码 |

### 4.3 CLI 退出码（exit_code）

当 `code = -3` 时，可通过 `exit_code` 进一步判断 CLI 失败原因：

| exit_code | 说明 |
|-----------|------|
| `0` | 执行完成（成功） |
| `1` | 命令行参数解析失败 |
| `2` | 用例文件不存在，或读取/校验后没有可执行用例 |
| `3` | 初始化失败，运行环境未就绪 |
| `5` | 执行过程中出现未处理异常 |

## 5. FTP 自动更新机制

### 5.1 FTP 连接配置

| 配置项 | 值 |
|--------|------|
| 协议 | FTP（显式 TLS/SSL 加密，即 FTPES） |
| 主机 | `devftp01.cmit.local` |
| 端口 | `9023` |
| 用户名 | `wangxf@cmgos.com` |
| 密码 | 存储于 Windows 凭据管理器（服务名：`CMGE_FTP`） |
| 远程目录 | `/dev-release/CMGE_Copilot/CMGE COPILOT` |

连接时使用 Python `ftplib.FTP_TLS`，并在登录后调用 `prot_p()` 将数据连接也升级为 TLS 加密。

### 5.2 版本文件夹命名规则

FTP 远程目录下的版本文件夹命名格式为：

```
{序号}_ForBuild_{描述}_{日期}
```

示例：`487_ForBuild_CMGE Service AI Agent-CI_20260224`

其中：
- **序号**：开头数字，如 `487`
- **日期**：末尾 8 位数字，如 `20260224`

### 5.3 版本排序规则

系统从 FTP 远程目录中筛选出所有符合命名规则的版本文件夹，然后按以下规则排序以确定"最新版本"：

1. **优先按日期降序**（日期越大越新，如 `20260301` > `20260224`）
2. **同日期按序号降序**（序号越大越新，如 `488` > `487`）
3. 排序后第一个即为最新版本

只有同时满足"开头为数字"和"末尾为 8 位数字"的文件夹才被视为有效版本文件夹。

### 5.4 版本比较与更新逻辑

```
读取本地 latest Version.txt → 获取本地版本名
          │
          ├─ 文件不存在 → 视为首次安装，直接下载安装最新版
          │
          └─ 读取成功 → 比较本地版本名与 FTP 最新版本名
                │
                ├─ 相同 → 返回 code=1，不执行测试
                └─ 不同 → 下载 → 安装 → 更新版本文件 → 执行测试
```

版本比较使用文件夹名的**完整字符串匹配**（非数值比较），因为日期+序号的组合保证了唯一性。

### 5.5 下载流程

1. 在 `D:\CMGE Copilot Store\temp\` 下创建以版本文件夹名命名的子目录
2. 从 FTP 下载该版本文件夹内的**所有文件**到该子目录
3. 下载完成后关闭 FTP 连接

### 5.6 静默安装流程

1. 在下载目录中找到 `CMGECopilot-Setup.msi`
2. 执行静默安装命令：`msiexec /i CMGECopilot-Setup.msi /q`
   - MSI 会自动安装到 `C:\CMGE Copilot\` 目录
3. 安装超时限制为 600 秒（10 分钟）

### 5.7 安装后验证

安装完成后，系统会检查以下文件是否存在：

- `C:\CMGE Copilot\API\CMGECopilot.API.exe`
- `C:\CMGE Copilot\UI\CMGECopilot.UI.exe`

两个文件都存在则验证通过。验证失败将终止流程并返回错误。

### 5.8 安装完成后的清理

安装成功并验证通过后：
1. 更新 `D:\CMGE Copilot Store\latest Version.txt` 为新版本文件夹名
2. 删除 `D:\CMGE Copilot Store\temp\` 整个临时目录

安装失败时临时文件**不会被删除**，以便排查问题。

### 5.9 FTP 流程异常处理

| 异常场景 | 行为 |
|----------|------|
| 凭据管理器中无密码 | 返回 code=-20，提示配置密码 |
| FTP 连接失败（网络/认证） | 返回 code=-20，终止流程 |
| FTP 目录下无有效版本文件夹 | 返回 code=-20，终止流程 |
| 下载过程中网络中断 | 返回 code=-20，清理临时文件 |
| MSI 安装失败（返回非 0） | 返回 code=-20，保留临时文件 |
| 安装后验证文件不存在 | 返回 code=-20，终止流程 |
| `latest Version.txt` 写入失败 | 仅记录日志警告，不终止流程 |

## 6. 完整请求处理流程

```
POST /api/trigger/auto-test
  │
  ├─ 获取互斥锁
  │   ├─ 失败 → 根据当前阶段返回 -10/-12/-13，提示调用方
  │   └─ 成功 → 继续
  │
  ├─ 解析 timeout、skip_update 参数
  │   ├─ timeout 无效 → 返回 -1
  │   └─ 继续
  │
  ├─ skip_update == false ?
  │   ├─ YES → FTP 版本检查与更新
  │   │   ├─ 连接 FTP（FTPS） → 失败返回 -20
  │   │   ├─ 获取最新版本 → 失败返回 -20
  │   │   ├─ 读取本地版本（不存在视为首次安装）
  │   │   ├─ 比较版本
  │   │   │   ├─ 相同 → 返回 code=1，释放锁
  │   │   │   └─ 有更新 → 继续
  │   │   ├─ 下载全部文件 → 失败返回 -20
  │   │   ├─ 关闭 FTP 连接
  │   │   ├─ MSI 静默安装 → 失败返回 -20
  │   │   ├─ 安装后验证 → 失败返回 -20
  │   │   ├─ 更新 latest Version.txt
  │   │   └─ 清理临时目录
  │   └─ NO → 跳过，继续
  │
  ├─ 前置校验：CLI 可执行文件
  │   ├─ 不存在 → 返回 -1
  │   └─ 无权限 → 返回 -2
  │
  ├─ 前置校验：用例 Excel 文件
  │   └─ 不存在 → 返回 -1
  │
  ├─ 执行 CLI 测试
  │   ├─ 超时 → 返回 -11
  │   ├─ 成功 → 返回 200
  │   └─ 失败 → 返回 -3
  │
  └─ 释放互斥锁
```

## 7. 调用示例

### 7.1 默认调用（含 FTP 版本检查）

#### curl

```bash
curl -X POST http://127.0.0.1:8090/api/trigger/auto-test \
  -H "Content-Type: application/json" \
  -d '{"task_id":"T001","remark":"触发更新+测试"}'
```

#### PowerShell

```powershell
$body = @{
    task_id = "T001"
    remark  = "触发更新+测试"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8090/api/trigger/auto-test" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

#### Python

```python
import requests

url = "http://127.0.0.1:8090/api/trigger/auto-test"
data = {"task_id": "T001", "remark": "触发更新+测试"}

response = requests.post(url, json=data)
result = response.json()
print(result)
```

### 7.2 跳过 FTP 检查（直接执行测试）

#### curl

```bash
curl -X POST http://127.0.0.1:8090/api/trigger/auto-test \
  -H "Content-Type: application/json" \
  -d '{"task_id":"T002","skip_update":true,"remark":"直接执行测试"}'
```

#### Python

```python
import requests

url = "http://127.0.0.1:8090/api/trigger/auto-test"
data = {"task_id": "T002", "skip_update": True, "remark": "直接执行测试"}

response = requests.post(url, json=data)
result = response.json()
print(result)
```

### 7.3 响应示例

#### 更新成功并执行测试

```json
{
  "code": 200,
  "msg": "AutoTestCopilot.CLI执行完毕",
  "task_info": {
    "task_id": "T001",
    "remark": "触发更新+测试"
  },
  "previous_version": "487_ForBuild_CMGE Service AI Agent-CI_20260224",
  "installed_version": "488_ForBuild_CMGE Service AI Agent-CI_20260301",
  "stdout": "Cases: ...\n用例执行完成...",
  "stderr": "",
  "exit_code": 0
}
```

#### 版本相同（未执行测试）

```json
{
  "code": 1,
  "msg": "当前版本已是最新，无需更新，未执行测试",
  "task_info": {
    "task_id": "T001",
    "remark": "触发更新+测试"
  },
  "current_version": "487_ForBuild_CMGE Service AI Agent-CI_20260224",
  "ftp_latest_version": "487_ForBuild_CMGE Service AI Agent-CI_20260224",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
}
```

#### FTP 连接失败

```json
{
  "code": -20,
  "msg": "FTP 更新流程失败: [Errno 11001] getaddrinfo failed",
  "task_info": {
    "task_id": "T001"
  },
  "error_detail": "[Errno 11001] getaddrinfo failed",
  "stdout": "",
  "stderr": "FTP 更新流程失败: [Errno 11001] getaddrinfo failed",
  "exit_code": -99
}
```

#### 正在安装新版本（请求被拒）

```json
{
  "code": -13,
  "msg": "当前正在静默安装CMGE Copilot新版本，请稍后再试",
  "task_info": {
    "task_id": "T002"
  },
  "stdout": "",
  "stderr": "当前正在静默安装CMGE Copilot新版本，请稍后再试",
  "exit_code": -99
}
```

#### CLI 不存在

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

## 8. 运行前提

在使用本服务前，请确保目标机器满足以下条件：

### 8.1 基础环境

1. **Python 环境**：已安装 Python 3.x
2. **Python 依赖**：`fastapi`、`uvicorn`、`keyring`
3. **.NET Framework 4.8**：AutoTestCopilot.CLI.exe 的运行依赖
4. **管理员权限**：服务需要以具有安装软件权限的账户运行（MSI 静默安装需要）

### 8.2 FTP 凭据

5. **Windows 凭据管理器**：已存储 FTP 密码
   - 服务名：`CMGE_FTP`
   - 用户名：`wangxf@cmgos.com`

### 8.3 被测软件

6. **外部程序**（安装后自动存在）：
   - `C:\CMGE Copilot\API\CMGECopilot.API.exe`
   - `C:\CMGE Copilot\UI\CMGECopilot.UI.exe`
7. **UI 窗口**：窗口标题包含 `CMGE Copilot`

### 8.4 测试工具

8. **CLI 程序**：`Release\AutoTestCopilot.CLI.exe` 存在
9. **用例文件**：`Release\Resources\a.xlsx` 存在且格式正确
10. **OCR 依赖（可选）**：`C:\Program Files\Tesseract-OCR\tesseract.exe`

### 8.5 存储目录

11. **版本存储目录**：`D:\CMGE Copilot Store` 存在（服务首次运行时会自动创建 `latest Version.txt`）

## 9. 日志

### 9.1 服务日志

- **路径**：`D:\auto_test_api\trigger_run.log`
- **格式**：`时间 | 级别 | 消息`
- **记录内容**：
  - 服务启动/重启（含版本号标识 v2.0）
  - 收到的触发请求及入参
  - FTP 连接状态（成功/失败）
  - FTP 版本比较结果
  - FTP 文件下载进度（每个文件的下载开始/完成）
  - MSI 静默安装执行结果（退出码、stdout、stderr）
  - 安装后验证结果
  - 本地版本文件更新
  - 临时目录清理
  - CLI 执行结果（退出码、标准输出、错误输出）
  - 前置校验失败信息

### 9.2 CLI 运行日志

CLI 自身的运行日志位于：
```
%LocalAppData%\AutoTestCopilot\logs
```

典型文件名：`AutoTestCopilot.CLI_yyyyMMdd_HHmmss.log`

## 10. 注意事项

1. **同步阻塞**：接口为同步调用，会等待整个流程（FTP 检查 + 下载 + 安装 + 测试）完成后再返回。新版本下载安装可能需要数分钟，调用方需设置合理的超时时间。
2. **单实例执行（互斥控制）**：服务内置互斥锁，同一时间只允许处理一个请求。若上一个任务尚未结束，新请求会立即返回错误，不会排队等待。返回的错误码会指示当前所处阶段（`-10` 测试中/`-12` 下载中/`-13` 安装中），调用方可据此判断何时重试。
3. **超时控制**：CLI 默认超时 30 分钟（1800 秒）。可在请求体的 `timeout` 字段中传入自定义秒数覆盖默认值。超时后子进程被强制终止并返回 `code: -11`。注意 `timeout` 仅控制 CLI 执行时长，不影响 FTP 下载和安装的时间。
4. **桌面会话**：CLI 依赖当前桌面会话进行 UI 自动化操作，请确保服务在有桌面会话的用户环境下运行，不要以 Windows 服务方式运行。
5. **相对路径**：CLI 可执行文件和用例文件均以 `test_trigger.py` 所在目录为基准进行相对路径定位，移动脚本时请保持 `Release` 目录的相对位置不变。
6. **防火墙**：服务监听 `0.0.0.0:8090`，请确保防火墙已开放 8090 端口。
7. **FTP 密码安全**：密码存储在 Windows 凭据管理器中，不以明文形式出现在代码或配置文件里。如需更换密码，请通过凭据管理器或 `keyring.set_password()` 更新。
8. **版本更新与测试的绑定关系**：默认模式下（`skip_update=false`），只有在 FTP 检测到新版本并成功安装后才会执行测试。如果版本相同，API 返回 `code=1` 而不执行测试。如需使用当前已安装版本直接执行测试，请传 `"skip_update": true`。
9. **升级策略**：当前 MSI 安装采用直接覆盖方式（不先卸载旧版本），该策略由 CMGE Copilot 开发人员保证可行性。如升级时遇到问题，需与开发人员协商调整方案。
