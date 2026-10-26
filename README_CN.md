# checkin

[English](README.md) · [简体中文](README_CN.md)

---

<a id="简体中文"></a>

## 简体中文

自动完成 **Trae SOLO CN**、**WorkBuddy** 以及**任意网站**的每日签到。

> 原名 `TWWB_checkin`，现正式更名为 `checkin`，仓库内相关内容已同步改名。如果你本地仍
> 指向旧仓库地址，可用 `git remote set-url origin <新仓库地址>` 切换。

### 功能特点

- **三类签到**：Trae SOLO CN、WorkBuddy，以及通用的网页签到
- **网页签到自动降级**：先尝试后台静默 HTTP 请求，静默无法确认成功时再用无头 Chrome/Edge 模拟
- **无需浏览器驱动**：网页兜底通过 Chrome DevTools Protocol (CDP) 直接驱动已安装的浏览器；
  只有在缺少 `websocket-client` 时才退回 Selenium
- **登录后自启**：登录后约 2 分钟才执行（不在登录瞬间运行，桌面环境已就绪）
- **详细日志**：每一步都带时间戳写入按天分割的日志文件
- **崩溃日志**：未捕获异常会完整记录堆栈并以退出码 3 结束

### 前提条件

- Windows 操作系统
- Python 3.11+（`.config` 使用标准库 TOML 解析器，需要 3.11+）
- Node.js 18+（仅 Trae 签到需要）
- 已安装 Trae SOLO CN 和/或 WorkBuddy（只在你勾选它们时才有要求）
- 已安装 Chrome 或 Edge（网页签到的浏览器兜底需要）
- 推荐 `pip install websocket-client` 以启用免驱动的网页浏览器引擎
  （未安装时会自动改用 Selenium）

### 快速开始

#### 1. 创建网页签到配置

站点列表是一个名为 `.config` 的 TOML 文件（已被 git 忽略）。先把仓库里的模板复制一份：

```cmd
cp .config.example .config
```

Windows `cmd.exe` 没有 `cp`，用：

```cmd
copy .config.example .config
```

然后编辑 `.config`，每个站点只需要 `name` 和 `url` 两个字段：

```toml
[[sites]]
name = "example"
url = "https://example.com/checkin"
```

如果是「登录即签到」的公益站（页面上没有签到按钮），再加一个 `login_only = true`：

```toml
[[sites]]
name = "Any Router"
url = "https://anyrouter.top/console/topup"
login_only = true
```

标记 `login_only = true` 后，只要页面成功打开就算签到成功，不会因为找不到签到按钮而
判失败或卡住。

`url` 填的是**登录后能看到签到按钮的页面链接**（例如 `https://wb.404-found.uk/hb/me`）。
默认做法是打开这个页面并替你点击按钮，因为有些接口带实时 token/签名，只有页面自己能生成。

如果签到其实就是一个普通的 JSON 接口（常被藏在某个标签页里，或由站点自己的 JS 触发），
直接声明它，就不用依赖按钮了：

```toml
[[sites]]
name = "404"
url = "https://wb.404-found.uk/hb/me"
checkin_api = "/hb/api/v1/checkin"   # POST 接口（相对 url 或绝对地址）
csrf_api    = "/hb/api/v1/me"        # 可选：返回 {"csrf": "..."}，作为 X-CSRF 头

[[sites]]
name = "Any Router"
url = "https://anyrouter.top/console/topup"
login_only   = true
checkin_api  = "/api/user/sign_in"
browser_only = true                   # 有 WAF，只有真实浏览器能过
```

`checkin_api` 先用已保存的 Cookie 静默调用一次；失败后会在**浏览器内部**再调一次，此时
WAF 的 JS 挑战已经通过、`localStorage` 里的登录态也在。`browser_only = true` 直接跳过
静默尝试（用于已知会拒绝普通 HTTP 客户端的站点）。

#### 如何判断签到链接

1. 用普通浏览器登录站点，打开能看到「签到」按钮的那个页面，把地址栏的值填进 `url`。
2. **不要**填 F12 → Network 里看到的那条请求：那种接口需要实时 token，直接 GET 是无效的。

每个站点登录一次，之后即可复用会话：

```cmd
python scripts\web_checkin.py --login example
```

会弹出一个浏览器窗口，登录完成后回到命令行按回车。Cookie 会保存到
`cookies\example.json`（已被 git 忽略），后续运行自动复用。

> 如果你只需要 Trae / WorkBuddy 签到，可以跳过这一步。

#### 2. 验证路径

```cmd
python scripts\test_paths.py
```

#### 3. 安装自动签到任务

```cmd
install_startup_task.bat
```

安装时会显示一个交互式**多选列表**：

```
============================================================
Select what the scheduled task should check in
============================================================
  UP/DOWN = move    SPACE = toggle    ENTER = confirm

  > [x] Trae SOLO CN
    [x] WorkBuddy
    [x] Web sites (.config)
```

**上下键**移动，**空格**勾选/取消，**回车**确认，至少需要勾选一项。
（原来的 `[3] Both` 已取消 —— 同时勾选两项即可达到同样效果。）

也可以直接在命令行传入（用于无人值守）：

```cmd
install_startup_task.bat trae,web quiet
```

可选值：`trae`、`workbuddy`、`web`、`apps`（= trae + workbuddy）、`all`（= 全部）、
`1`/`2`/`3`（= trae / workbuddy / web），或任意逗号组合。

接着会询问**什么时候执行**：

```
============================================================
When should the check-in run?
============================================================
  [1] After logon (current behaviour, with a short delay)
  [2] Every day at a specific time
Choice [1/2] (default 1):
```

选 `[2]` 后输入时间，**24 小时制**（`20:15`、`2130`）和 **12 小时制**
（`9:30AM`、`8:30 PM`）都支持，会自动归一成 24 小时制。命令行也可以直接给时间，
例如 `install_startup_task.bat all 21:30 quiet` 或 `install_startup_task.bat all logon quiet`。

#### 4. 测试签到

```cmd
python scripts\auto_checkin.py
```

### 网页签到

`.config` 中的每个站点都按两级处理：

1. **静默** —— 带已保存的 Cookie 用 `requests` `GET` 该 `url`；若页面显示“已签到”或“成功”，
   直接完成，全程不弹窗。站点声明了 `checkin_api` 时，改为调用该 JSON 接口而不是解析页面。
2. **无头浏览器** —— 第一级无法确认时（401/403、跳转登录页、文案无法判断），用无头
   Chrome/Edge 打开 `url`，点击签到按钮（`checkin_api` 站点则在页面内调用接口）并读取结果，
   截图保存到 `screenshots\`（已被 git 忽略）。

> 带 token 的站点（大多数）会直接从第一级落到第二级，这是预期行为——你只需要填页面链接，
> 不需要填接口。

标记了 `login_only = true` 的站点会走兜底策略：页面上没有签到按钮时，只要浏览器里页面成功
打开就记为**成功**，而不是「找不到签到按钮」失败。静默级不再凭一个 200 就相信这类站点：
登录表单、WAF 挑战页和真实面板都会返回 200，只有浏览器能分辨。

常用命令：

```cmd
python scripts\web_checkin.py                  # 签到所有站点
python scripts\web_checkin.py --site example   # 只签到某个站点
python scripts\web_checkin.py --login example  # 登录一次并保存 Cookie
python scripts\web_checkin.py --list           # 列出已配置站点
python scripts\web_checkin.py --dry-run        # 只校验 .config，不签到
python scripts\web_checkin.py --headful        # 显示浏览器窗口（调试）
python scripts\web_checkin.py --headless       # 强制使用无头浏览器
python scripts\web_checkin.py --force-browser  # 跳过静默尝试
python scripts\web_checkin.py --silent-only    # 绝不打开浏览器
```

### 项目结构

```
checkin/
├── config.py                  # 配置文件（路径、超时、网页选项）
├── .config                    # 网页站点列表（TOML，已被 git 忽略，从 .config.example 复制）
├── .config.example            # .config 的模板（提交到仓库）
├── cookies/                   # 保存的 Cookie + 浏览器 profile（已被 git 忽略）
├── screenshots/               # 网页签到截图（已被 git 忽略）
├── logs/                      # 按天日志目录（已被 git 忽略）
│   ├── auto_checkin_YYYY-MM-DD.log
│   └── web_checkin_YYYY-MM-DD.log
├── scripts/
│   ├── auto_checkin.py        # 主调度脚本（含日志/崩溃捕获）
│   ├── web_checkin.py         # 网页签到（静默 HTTP -> 无头浏览器）
│   ├── browser_engine.py      # CDP / Selenium 浏览器引擎
│   ├── select_targets.ps1     # 安装脚本使用的交互式目标选择器
│   ├── test_paths.py          # 路径验证
│   ├── diagnose_workbuddy.py  # WorkBuddy 诊断（只截图不点击）
│   └── full_test.py           # 系统测试
├── patches/                   # 第三方子模块的本地补丁快照
├── trae-daily-checkin/        # Trae 库（第三方，见 THIRD_PARTY_NOTICES.md）
├── workbuddy-checkin/         # WorkBuddy 库（第三方，见 THIRD_PARTY_NOTICES.md）
├── install_startup_task.bat   # 安装任务（登录 + 2 分钟延迟）
├── uninstall_startup_task.bat # 卸载任务
├── test_checkin.bat           # 测试签到
└── info.bat                   # 显示信息
```

### 日志与退出码

每次运行都会追加写入 `logs\auto_checkin_YYYY-MM-DD.log`，网页步骤另写
`logs\web_checkin_YYYY-MM-DD.log`（UTF-8，保留 30 天）。日志包含：运行环境（会话 ID、
屏幕分辨率、开机后经过时间、各路径解析结果）、每个子进程的完整命令与 stdout/stderr 和
退出码、以及任何异常的完整堆栈。

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部签到成功，或至少一个成功 |
| `1` | 全部签到失败 / 应用或脚本路径不存在 |
| `2` | 网页签到配置问题（`.config` 缺失或格式错误） |
| `3` | 脚本异常崩溃（日志中有 `[CRASH]` 段落） |

计划任务的上次退出码也可在任务计划程序中查看
（`schtasks /Query /TN AutoCheckinOnStartup /V /FO LIST` 的“上次结果”字段）。

### 配置说明

编辑 `config.py` 配置应用路径、超时和网页浏览器选项：

```python
TRAE_EXE = r"你的Trae路径"
WORKBUDDY_EXE = r"你的WorkBuddy路径"
TRAE_TIMEOUT = 120
WORKBUDDY_TIMEOUT = 60

WEB_CONFIG_PATH = os.path.join(PROJECT_DIR, ".config")
WEB_TIMEOUT = 30           # 单次请求超时
WEB_VERIFY_TIMEOUT = 15    # 点击后等待结果的秒数
WEB_CHECKIN_TIMEOUT = 300  # 整个网页步骤的超时
WEB_HEADLESS = True        # False = 显示浏览器窗口（调试）
WEB_BROWSER = "auto"       # "chrome" 强制 Chrome，"edge" 强制 Edge
```

网页站点列表在 `.config` 中编辑。

### 常用命令

| 命令 | 说明 |
|------|------|
| `python scripts\test_paths.py` | 测试路径 |
| `python scripts\auto_checkin.py` | 手动签到（所有已选目标） |
| `python scripts\auto_checkin.py --target trae,web` | 只签到指定目标 |
| `python scripts\web_checkin.py --login example` | 登录网页站点一次并保存 Cookie |
| `python scripts\full_test.py` | 系统测试 |
| `install_startup_task.bat` | 安装任务（交互式多选 + 计划时间） |
| `install_startup_task.bat trae,web` | 不询问直接安装 |
| `install_startup_task.bat all 21:30` | 安装每天 21:30 执行的任务 |
| `uninstall_startup_task.bat` | 卸载任务 |

### 故障排除

1. **路径错误**：编辑 `config.py` —— 日志里会明确写出缺失的路径
2. **签到失败**：确保应用已登录
3. **任务不执行**：检查 Python/Node.js 在 PATH 中
4. **任何无法解释的失败**：打开 `logs\auto_checkin_YYYY-MM-DD.log`，
   里面有完整环境信息、每个子进程退出码和崩溃堆栈
5. **WorkBuddy 点击无反应**：它的点击坐标是按 1920x1080 硬编码的，
   分辨率不一致时脚本会输出 WARN 提示
6. **WorkBuddy 提示"界面无变化"或界面上看不到签到结果**：运行
   `python scripts\diagnose_workbuddy.py`，查看生成的截图并修正 `config.py` 的
   `WORKBUDDY_CHECKIN_X/Y`
7. **`.config` 缺失或为空**：执行 `cp .config.example .config`，再添加 `[[sites]]` 段落；
   网页步骤会以退出码 `2` 明确报错
8. **网页签到总是走到浏览器**：还没有 Cookie —— 先运行
   `python scripts\web_checkin.py --login <站点名>`，静默方式需要已保存的会话
9. **网页浏览器起不来**：安装 Chrome 或 Edge；并执行 `pip install websocket-client`
   以启用免驱动的 CDP 引擎（没有它就需要 Selenium 和匹配的驱动）
10. **网页兜底用了 Edge 而不是 Chrome**：在 `config.py` 里设 `WEB_BROWSER = "chrome"`。
    默认永远先试 Chrome；只有在 Chrome 起不来（例如 profile 被残留进程占用）时才用 Edge
10. **安装脚本看起来没生效**：打开 `logs\install_task.log`，里面有提权状态、解析到的
    Python/Node 路径、以及完整的 `schtasks` 命令与输出/退出码。UAC 被取消时现在会明确
    报错，不再静默关窗。登录触发的任务只在**登录时**执行，未重新登录/重启前不会跑；
    每天固定时间的任务会在设定时间且电脑开着时执行。
11. **根目录出现删不掉的 `nul` 文件**：这是从 POSIX shell（git-bash/WSL）里执行了
    `2>nul` 这类重定向造成的 —— shell 不认识 Windows 的 NUL 设备，就真建了一个文件；
    Windows 又把该名字解析成设备，所以 `del`/`rm`/`Remove-Item` 都无效。执行
    `python scripts\clean_strays.py` 删除（每次签到运行也会自动清理）。

### 技术细节

- **Trae**：Chrome DevTools Protocol (CDP) + Node.js
- **WorkBuddy**：Win32 API (ctypes) + Python
- **网页**：`requests`（静默层）→ 通过已安装 Chrome/Edge 的 CDP（无头层），
  必要时退回 Selenium

### 注意事项

- 默认计划是**用户登录后 2 分钟**执行（可改：`install_startup_task.bat` 顶部的
  `STARTUP_DELAY`）。也可以装成**每天固定时间**执行（支持 24 小时制和 12 小时制 AM/PM）——
  安装脚本会询问，或在命令行直接给 `logon` / `21:30`
- 计划任务的工作目录是 `C:\Windows\System32`，所有路径都基于项目目录解析，
  与当前目录无关
- WorkBuddy 坐标在 `config.py`（`WORKBUDDY_MENU_X/Y`、`WORKBUDDY_CHECKIN_X/Y`）中配置，
  由 `scripts/auto_checkin.py` 以环境变量注入到第三方脚本中
- `WORKBUDDY_SKIP_MENU = True` 表示直接点首页的签到按钮，跳过头像菜单流程
- WorkBuddy 签到自带校验（`WORKBUDDY_VERIFY = True`）：先等签到按钮渲染出来，
  确认窗口真的在前台，再点击，然后对比点击前后的截图，界面没变化就重试
  （最多 `WORKBUDDY_MAX_TRIES` 次）
- `python scripts\diagnose_workbuddy.py` 会截取真实 WorkBuddy 窗口并在配置坐标处画十字，
  **全程不点击**
- 网页兜底会点击第一个可见、文案像签到控件的按钮/链接（“签到”“打卡”“领取”“check in”等），
  并跳过已经显示“已签到 / already”的控件
- 重新校准坐标：把鼠标悬停在目标上，然后执行
  `python -c "import ctypes,ctypes.wintypes as w,time; u=ctypes.windll.user32; time.sleep(5); p=w.POINT(); u.GetCursorPos(ctypes.byref(p)); print(p.x, p.y)"`
  （用 `python` 而不是 PowerShell —— PowerShell 不感知 DPI，取到的坐标会被缩放）
- 首次使用需手动登录
- Trae 调试端口仅监听 127.0.0.1

### 第三方代码引用声明

本仓库收录以下两个开源项目。Trae 与 WorkBuddy 签到实现的所有功劳归上游作者所有；本项目
原创部分仅为封装与调度层（`config.py`、`scripts/`、`*.bat`）。`trae-daily-checkin/` 带 3 处
本地修复（等待 CDP page target、轮询账户 UI、让 `--close` 真正生效）；`workbuddy-checkin/`
带有少量本地补丁（点击坐标与签到流程开关均支持环境变量覆盖，从而可由 `config.py` 统一配置），
详见 THIRD_PARTY_NOTICES.md。

| 目录 | 上游仓库 | 作者 | 许可证 |
| --- | --- | --- | --- |
| `trae-daily-checkin/` | [BlueChonk/trae-daily-checkin](https://github.com/BlueChonk/trae-daily-checkin) | Cecilia | MIT |
| `workbuddy-checkin/` | [GitOfUser/workbuddy-checkin](https://github.com/GitOfUser/workbuddy-checkin) | GitOfUser | 上游未提供许可证文件（版权归原作者所有） |

版本与提交信息、商标说明详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## License / 许可证

本项目原创部分（封装与调度层）采用 MIT License。
收录的第三方代码版权归各自作者所有，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
