# AutoTestCopilot CLI 使用说明

## 1. 可执行文件

```text
AutoTestCopilot.CLI.exe
```

`AutoTestCopilot.CLI` 是一个控制台程序。
它通过项目引用复用 `AutoTestCopilot` 主项目中的用例加载、UI 自动化、OCR、日志和结果归档能力。

## 2. 运行前提

运行前请确认目标机器满足以下条件：

1. 已安装 `.NET Framework 4.8`
2. 以下外部程序路径存在：

```text
C:\CMGE Copilot\API\CMGECopilot.API.exe
C:\CMGE Copilot\UI\CMGECopilot.UI.exe
```

3. UI 窗口标题包含：

```text
CMGE Copilot
```

4. 如需 OCR 兜底，默认依赖：

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

如果该路径不存在，程序仍可运行，但 OCR 兜底能力不会生效。

## 3. 基本用法

```powershell
AutoTestCopilot.CLI.exe [--cases <xlsxPath>]
                         [--resume | --clean-checkpoint]
                         [--image-debug true|false]
                         [--share-out <UNC>]
                         [--no-share-out]
```

程序启动后会输出当前运行参数，例如：

- `Cases`
- `Resume`
- `CleanCheckpoint`
- `ImageDebug`
- `ShareOut`

## 4. 参数说明

### `--cases <xlsxPath>`

指定测试用例 Excel 文件。

示例：

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx
```

如果不传，程序会按如下路径寻找默认用例：

```text
当前 exe 目录\Resources\DefaultCases.xlsx
```

找不到时，进程返回失败。

---

### `--resume`

断点续跑。

行为：

- 保留现有 `checkpoint` 文件
- 跳过已完成用例
- 从中断位置继续执行

---

### `--clean-checkpoint`

清理断点并从头执行。

行为：

- 删除已有 `checkpoint` 文件
- 从第一条合规用例重新执行

这是默认行为。

---

### `--image-debug true|false`

控制图像调试开关。

对应代码行为：

- 调用 `ChatUiInteractor.SetImageDebugEnabled(...)`
- 记录输入框模板搜索区域截图
- 记录复制图标搜索区域截图
- 保留 OCR 调试输出文件（如触发 OCR）

支持值：

- `true` / `false`
- `1` / `0`

示例：

```powershell
AutoTestCopilot.CLI.exe --image-debug true
```

---

### `--share-out <UNC>`

指定共享目录归档根路径。

程序结束后会把本次运行产物复制到共享目录下自动生成的子目录中。子目录命名规则为：

```text
<用户名>_yyyyMMdd_HHmmss_fff_<机器名>
```

示例：

```powershell
AutoTestCopilot.CLI.exe --share-out \\server\share\AutoTestLogs
```

---

### `--no-share-out`

禁用共享目录归档。

启用后：

- 不再复制运行产物到共享目录
- 仅保留本地日志和结果文件

## 5. 默认值

如果不传参数，当前默认行为如下：

- `CasesXlsxPath`：`当前 exe 目录\Resources\DefaultCases.xlsx`
- `Resume = false`
- `CleanCheckpoint = true`
- `ImageDebugEnabled = false`
- `EnableShareOut = true`
- `ShareOutRoot = \\10.0.19.101\共享磁盘\研发测试部 DEV\WangXiaofeng\AutoTestCopilot Log`
- `CopilotWindowTitle = CMGE Copilot`

说明：

- `CopilotWindowTitle` 当前没有独立命令行参数
- `--resume` 与 `--clean-checkpoint` 互斥

## 6. 退出码

当前 CLI 退出码约定如下：

- `0`：执行完成
- `1`：命令行参数解析失败
- `2`：用例文件不存在，或读取/校验后没有可执行用例
- `3`：初始化失败，运行环境未就绪
- `5`：执行过程中出现未处理异常

## 7. 执行流程概览

当前 CLI 的主要执行流程如下：

1. 解析命令行参数
2. 初始化日志文件
3. 解析或定位用例文件
4. 读取并校验 Excel，用 `XlsxCaseLoader` 生成合规用例 JSON
5. 初始化运行环境
   - 显示桌面
   - 启动 API 进程
   - 重启并拉起 UI 进程
   - 查找 `CMGE Copilot` 窗口
   - 检测 `API正常`
6. 构建输入框模板候选与复制图标模板候选
7. 逐条执行用例
8. 生成结果文件、桌面 Excel/CSV 副本、结构化报告
9. 如启用共享归档，则复制运行产物到共享目录
10. 收尾关闭 UI 与 API 进程

## 8. 常用示例

### 从头执行

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx --clean-checkpoint
```

### 断点续跑

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx --resume
```

### 开启图像调试

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx --image-debug true
```

### 禁用共享归档

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx --no-share-out
```

### 指定共享归档目录

```powershell
AutoTestCopilot.CLI.exe --cases C:\Temp\cases.xlsx --share-out \\10.0.19.101\共享磁盘\研发测试部 DEV\WangXiaofeng\AutoTestCopilot Log
```

## 9. 日志与调试输出

### 运行日志文件

目录：

```text
%LocalAppData%\AutoTestCopilot\logs
```

典型文件名：

```text
AutoTestCopilot.CLI_yyyyMMdd_HHmmss.log
```

日志中会记录：

- 初始化过程
- 输入框模板搜索顺序
- 复制图标模板候选
- API 检测结果
- 用例执行状态
- 结果文件路径
- 共享归档结果

### 图像调试截图

当使用：

```powershell
--image-debug true
```

时，`%TEMP%` 下可能生成：

```text
search_region_*.png
copy_region_*.png
ocr_tess_img_*.png
ocr_tess_out_*.txt
```

其中：

- `search_region_*.png`：输入框模板匹配搜索区域
- `copy_region_*.png`：复制图标匹配搜索区域
- `ocr_tess_*`：OCR 调试中间文件

## 10. 运行产物

CLI 运行过程中或结束后，通常会生成以下文件：

- 合规用例 JSON
- 执行结果 JSON
- 结构化测试报告 JSON
- 桌面 Excel 或 CSV 副本
- checkpoint 文件
- 运行日志文件

常见位置包括：

- `%TEMP%`
- `%LocalAppData%\AutoTestCopilot\logs`
- 桌面
- 共享归档目录（如启用）

典型文件名示例：

```text
cases_executed_yyyyMMdd_HHmmss_fff.json
cases_report_yyyyMMdd_HHmmss_fff.json
cases_executed_checkpoint.json
cases_progress_checkpoint.json
```

## 11. 共享归档内容

启用共享归档时，程序会尝试归档以下文件：

- 当前运行日志
- 合规用例 JSON
- 执行结果 JSON
- 结构化报告 JSON
- 桌面 Excel 或 CSV 副本
- `cases_executed_checkpoint.json`
- `cases_progress_checkpoint.json`

如果共享目录创建或复制失败，只会写日志，不会单独改变主执行退出码。

## 12. 注意事项

1. `--resume` 与 `--clean-checkpoint` 不能同时使用。
2. `--image-debug` 必须显式传 `true/false` 或 `1/0`。
3. 当前 CLI 不支持短参数，如 `-debug`。
4. 未指定 `--cases` 时，必须确保 `Resources\DefaultCases.xlsx` 存在。
5. CLI 会主动启动并关闭外部 `CMGE Copilot` API/UI 进程。
6. CLI 依赖当前桌面会话、窗口标题和 UI 自动化行为，建议在无人打断的桌面环境下执行。
