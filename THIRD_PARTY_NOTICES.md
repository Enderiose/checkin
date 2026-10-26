# 第三方代码引用声明 / Third-Party Notices

本仓库（`checkin`，原名 `TWWB_checkin`）以**上游副本**形式收录了以下第三方项目；本地改动均在下文逐条注明。
本仓库仅提供封装与调度层（`config.py`、`scripts/`、`*.bat`、`README.md`）；
所有签到实现的功能、算法与技术路线的著作权归上游作者所有。

This repository vendors the following upstream projects. Every local modification is listed explicitly below.
Only the wrapper/scheduling layer (`config.py`, `scripts/`, `*.bat`, `README.md`)
is original to this project. All copyright in the check-in implementations
belongs to the respective upstream authors.

---

## 1. trae-daily-checkin

| 项目 / Item | 内容 / Value |
| --- | --- |
| 收录目录 / Vendored path | `trae-daily-checkin/` |
| 上游仓库 / Upstream | https://github.com/BlueChonk/trae-daily-checkin |
| 作者 / Author | Cecilia（见 `trae-daily-checkin/package.json` 的 `author` 字段） |
| 版本 / Version | 1.0.0（`package.json`） |
| 许可证 / License | MIT |
| 本地是否修改 / Local modifications | **有本地修复 / Local fixes applied**（2026-09-27）：① `connectCDP()` 原先只查一次 `/json`，在“端口已监听、workbench 的 `page` target 尚未出现”时会直接报 `未找到 page 类型的 CDP target`（即 Trae 未运行时由脚本拉起的场景几乎必然失败）——改为新增 `waitForPageTarget()` 轮询等待（最长 30s）；② 打开账户菜单后立刻读取签到按钮，而弹层容器先出现、签到行后渲染，会被误判成“类名已变化”——改为依次轮询 `accountTrigger` / `accountPopover` / `accountCheckinButton`（各最长 15s）；③ `CLOSE_AFTER_CHECKIN`（`--close`）原先解析后从未被使用，导致不传 `--close` 也会关闭 Trae——改为仅在该开关打开时关闭。上游的启动、定位、CDP 连接与签到点击流程均保留。 |
| 仓库跟踪方式 / How it is tracked | 2026-09-27 起作为父仓库的普通文件跟踪。此前索引中把它记为 submodule（gitlink），但磁盘上既无 `.git` 也无 `.gitmodules`，该目录实际上从未被跟踪，全新 clone 拿不到任何文件。 |

### 用途 / Purpose

Trae SOLO CN 每日签到自动化。通过启动参数开启 Chromium 远程调试端口，
再经由 Chrome DevTools Protocol (CDP) 操控页面 DOM 完成签到点击。

本仓库引用入口：`config.py` 的 `TRAE_CHECKIN_SCRIPT`
→ `trae-daily-checkin/src/auto-checkin.mjs`（由 `scripts/auto_checkin.py` 调用）。

### 许可证原文 / License text

上游 `package.json` 声明 `"license": "MIT"`，但仓库内未附 `LICENSE` 文件。
如上游后续补充许可证文件，以该文件为准。

MIT License（摘要）

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

---

## 2. workbuddy-checkin

| 项目 / Item | 内容 / Value |
| --- | --- |
| 收录目录 / Vendored path | `workbuddy-checkin/` |
| 上游仓库 / Upstream | https://github.com/GitOfUser/workbuddy-checkin |
| 作者 / Author | GitOfUser |
| 收录提交 / Vendored commit | `cb9f5e21a1fc447a59d16c1184dc671727058656`（`fix(scripts/checkin_py): adjust checkin mouse coordinates`） |
| 许可证 / License | 上游未提供许可证文件，版权归原作者所有（All rights reserved） |
| 本地是否修改 / Local modifications | **有本地补丁 / Local patches applied**（2026-09-22）：① 点击坐标支持环境变量覆盖 `WORKBUDDY_MENU_X/Y`、`WORKBUDDY_CHECKIN_X/Y`，未设置时保持上游原值 207/983 与 112/487；② 新增流程开关 `WORKBUDDY_SKIP_MENU`，可在首页直接签到、跳过头像菜单（默认 `0` = 上游原始流程）；③ 新增点击校验 `WORKBUDDY_VERIFY`：等按钮渲染、确认窗口在前台、点击后对比截图、无变化则重试，找不到按钮则按"已签到"处理（默认 `1`；设 `0` 退回上游盲点行为）；④ 启动时打印坐标/流程/校验状态与窗口矩形；⑤ 主流程包裹 `try/except`，异常时弹窗提示。上游的启动、查找窗口、关闭窗口与点击序列均保留。另生成运行时缓存 `scripts/__pycache__/`。 |

### 用途 / Purpose

WorkBuddy 每日签到自动化。通过 Windows Win32 API（Python `ctypes` / PowerShell）
模拟鼠标点击完成签到，另附 Linux/macOS 的 Playwright/shell 实现。

本仓库引用入口：`config.py` 的 `WORKBUDDY_CHECKIN_SCRIPT`
→ `workbuddy-checkin/scripts/checkin_py.py`（由 `scripts/auto_checkin.py` 调用）。

### 使用注意 / Usage notes

本地补丁快照 / Patch snapshot：`patches/workbuddy-checkin-local.patch`。
`workbuddy-checkin/` 是独立子模块，其 `origin` 指向上游仓库，本地补丁不适合提交到上游，
因此以补丁文件形式随主仓库一起版本化，便于重放与回溯：

```cmd
cd workbuddy-checkin
git checkout cb9f5e2
git apply ../patches/workbuddy-checkin-local.patch
```

本仓库对 `checkin_py.py` 的本地补丁涉及：坐标读取方式（环境变量覆盖，默认值不变）、
流程开关（默认保持上游的"点头像→等菜单→点签到"步骤）与点击校验（默认开启，
可用 `WORKBUDDY_VERIFY=0` 完全退回上游的"盲点"行为）；上游的窗口查找/启动/关闭与
点击时序均未改动。如需与上游对比，可在 `workbuddy-checkin/` 目录执行 `git diff`。
上游仓库未声明开源许可证，因此在未获得作者授权前：

- 请勿再分发、商用或以其名义发布衍生版本；
- 本仓库仅作个人本地使用的原样收录；
- 如需引用或分发，请先联系上游作者获取授权。

The upstream repository provides **no license file**. Until the author grants a
license, do **not** redistribute or use this code commercially. It is vendored
here for personal, local use only. Contact the upstream author for permission.

---

## 免责声明 / Disclaimer

- 本项目及其引用的第三方代码均为非官方的个人自动化脚本，与 Trae SOLO CN、WorkBuddy
  各自的开发/运营方无任何隶属或背书关系。
- 商标、产品名称（Trae、SOLO CN、WorkBuddy 等）归其各自所有者所有，仅用于说明用途。
- 自动化点击可能违反相关服务条款，使用者需自行承担风险。