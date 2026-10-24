# SignalRGB Home Assistant 集成：WebPipe 版

[English](README.md) | **简体中文**

不需要 SignalRGB Pro 订阅，就能在 Home Assistant 里控制 [SignalRGB](https://signalrgb.com)。

本项目改自 [hyperb1iss/signalrgb-homeassistant](https://github.com/hyperb1iss/signalrgb-homeassistant)。原版走 SignalRGB 的 HTTP API（16038 端口），这个接口只对 Pro 用户开放。本版改走 SignalRGB 桌面界面自己用的本地通道，所以免费版能在窗口里做到的事，在 Home Assistant 里也都能做。

## 和原版的区别

| | 原版 1.x | 本版 2.x |
| --- | --- | --- |
| SignalRGB 版本 | 必须 Pro | 免费版即可 |
| 通信方式 | `:16038` 的 HTTP API | 经中继连到 `127.0.0.1:16036` 的 WebPipe（QWebChannel） |
| 状态更新 | 每 5 分钟轮询一次 | 实时推送（`local_push`） |
| 开关与亮度 | 全局画布开关（Pro API） | 逐个设置每个设备和组件的亮度 |
| 当前灯效 | 只是灯实体里的一个属性 | 独立的灯效下拉框，灯效的每个参数各有一个实体 |
| 其他 | — | 灯效轮播开关和间隔，Windows 命令行工具 `srgb` |

## 工作原理

```
Home Assistant ──WebSocket──▶ PC 上的 webpipe_relay.py (:16046) ──▶ SignalRGB WebPipe (127.0.0.1:16036)
```

SignalRGB 桌面程序通过一个叫 **WebPipe** 的 [QWebChannel](https://doc.qt.io/qt-6/qtwebchannel-javascript.html) WebSocket，把它的核心对象（灯效、设备、布局……）发布出来，它自己的界面就是通过这个通道控制程序的，没有 Pro 校验。WebPipe 只监听本机，所以由 `windows/webpipe_relay.py` 把它转发到局域网，并且只接受你指定的 IP。

- **灯效**：调用 `lighting.setAlwaysEffect(名称)`，和 SignalRGB 界面切换灯效时调用的是同一个方法。下一个、上一个、随机分别对应 `goForward()`、`goBackward()`、`goCrazy()`。
- **开关和亮度**：每个灯光端点（每个设备，以及灯控通道上的每个组件）都有一个可写的 `Brightness`。*关灯*时把它们全部设为 0，并记下各自原来的亮度；*开灯*时按记下的值恢复。当前灯效始终不变。
- **灯效参数**：用 `itemList()` 读取当前灯效的参数列表，直接写每个参数的 `value`。SignalRGB 在灯效加载过程中会重建这些参数对象，所以集成订阅了参数列表的变化信号，变化后重新读取。

## 运行要求

- Windows 上的 SignalRGB，免费版即可。测试版本 **2.5.82**。
- 同一台 PC 上的 Python 3.11+，用来跑中继，只用到标准库。
- Home Assistant **2026.4** 或更新。测试版本 **2026.9.4**。

## 安装

### 1. 在 SignalRGB 所在的 PC 上运行中继

把 [`windows/webpipe_relay.py`](windows/webpipe_relay.py) 复制到 PC 上并启动，`--allow` 后面填 Home Assistant 主机的 IP：

```powershell
python webpipe_relay.py --allow 192.168.1.10
```

- `--allow` 必填，可以写多次；其他 IP 的连接一律拒绝。
- `--port` 改局域网端口，默认 `16046`。
- 日志写到脚本旁边的 `webpipe_relay.log`。
- 如果 Windows 弹窗询问，或者 Home Assistant 连不上，记得在 Windows 防火墙里放行这个端口的入站 TCP。

想在每次登录后自动在后台启动，可以注册一个计划任务（在 PowerShell 里运行一次；路径和 IP 改成你的）：

```powershell
$py = (Get-Command pythonw).Source
$action = New-ScheduledTaskAction -Execute $py -Argument '"C:\path\to\webpipe_relay.py" --allow 192.168.1.10'
Register-ScheduledTask -TaskName 'SignalRGB WebPipe relay' -Action $action -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
```

最好在路由器里给这台 PC 固定 IP（DHCP 保留），这样 Home Assistant 总能找到它。

### 2. 安装集成

#### 用 HACS 安装（推荐）

1. **HACS → 右上角 ⋮ → 自定义存储库（Custom repositories）**
2. 存储库填 `https://github.com/vshijiav/signalrgb-homeassistant`，类型选 **Integration**，点 **添加**
3. 在 HACS 里打开 **SignalRGB (WebPipe edition)**，点 **下载**，然后重启 Home Assistant。

之后 HACS 会跟着这个仓库的 Release 走，更新来自本版，不会再被原版覆盖。

> **之前通过 HACS 装过原版？** 两者用的是同一个 `signalrgb` 域名，要先让 HACS 不再跟踪原版。如果想保留已有的集成配置，不要在 HACS 里对原版点 *删除*，那会把 `custom_components/signalrgb` 整个目录删掉。直接下载本版覆盖上去就行；之后 HACS 对原版条目提示的更新一律忽略。

#### 手动安装

把 `custom_components/signalrgb/` 复制到 Home Assistant 的 `config/custom_components/` 目录下，然后重启 Home Assistant。

### 3. 在 Home Assistant 里添加

**设置 → 设备与服务 → 添加集成 → SignalRGB**，填入 PC 的 IP 和中继端口（`16046`）。

## 实体

| 实体 | 作用 |
| --- | --- |
| `light.signalrgb_*` | 所有设备的开关和亮度；灯效列表是全部已安装的灯效 |
| `select.*_effect` | 当前灯效，选别的就切换过去 |
| `select.*_layout` | SignalRGB 里保存的布局 |
| `select.*_effect_preset` | 当前灯效保存的预设（没有预设时显示不可用） |
| `button.*_next_effect` / `_previous_effect` / `_random_effect` | 下一个 / 上一个 / 随机灯效 |
| `switch.*_effect_rotation` | 按 SignalRGB 的定时器自动轮播灯效 |
| `number.*_effect_rotation_interval` | 轮播间隔（秒，最少 10） |
| 灯效参数 | 当前灯效的每个参数各一个实体（见下表） |

**灯效参数**跟着当前灯效走。某个参数第一次出现时（即第一次运行带这个参数的灯效时），会自动生成对应的实体：

| SignalRGB 参数类型 | 实体 |
| --- | --- |
| 滑块 / 色相 | `number`（滑块，最小值、最大值、步长都和灯效里的一致） |
| 开关 | `switch` |
| 下拉 | `select` |
| 颜色 | `text`（`#rrggbb`） |

当前灯效没有的参数会被自动隐藏，等切到用到它们的灯效时再自动显示。你自己手动隐藏的实体不会被动。

## Windows 命令行工具

[`windows/srgb.cmd`](windows/srgb.cmd) 可以在终端或计划任务里控制 SignalRGB，走的也是 WebPipe：

```powershell
srgb status          # on (Aurora)
srgb off             # 记下当前灯效，切到关灯灯效
srgb on              # 恢复记下的灯效
srgb toggle
srgb effect "Aurora"
```

- `off` 的做法是切到一个已安装的“关灯”灯效，默认是 `AA关灯`。想换成别的，加 `-OffEffect "Good Night!"`（或任意其他灯效名）。
- `status` 是通过 SignalRGB 内置的 MCP 读取当前灯效的，所以要保持 **设置 → Application → AI Integration → Model Context Protocol** 开启。
- 记下的灯效保存在脚本旁边的 `state.json`。

## 安全

WebPipe 暴露的是整个程序，包括你登录的 SignalRGB 账号信息。中继只转发 `--allow` 里指定 IP 的连接。千万不要把中继端口映射到公网。

## 局限

- WebPipe 是 SignalRGB 内部给界面用的通道，不是公开 API。SignalRGB 升级后，这里用到的对象可能被改名或修改。
- “关灯”是把每个设备的亮度调到 0，而不是关闭 SignalRGB 的画布；灯效其实仍在以 0 亮度运行。
- PC 上的中继必须在运行。中继或 SignalRGB 恢复后，Home Assistant 会自动重连。

## 开发

```bash
uv sync
uv run pytest
uv run ruff check custom_components tests
```

测试用一个模拟的 QWebChannel 服务器来跑客户端，不需要真的装 SignalRGB。

## 致谢与许可

基于 Stefanie Jane 的 [hyperb1iss/signalrgb-homeassistant](https://github.com/hyperb1iss/signalrgb-homeassistant)（Apache 2.0 许可）。本版新增了 WebPipe 通信层、新的实体和 Windows 端工具，详见 [NOTICE](NOTICE) 和 [CHANGELOG](CHANGELOG.md)。

采用 Apache License 2.0，见 [LICENSE](LICENSE)。

与 WhirlwindFX / SignalRGB 官方无关。只使用了免费版 SignalRGB 在自己窗口里就提供的功能。
