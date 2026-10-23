# Clipboard Bridge · 跨系统剪贴板助手

把你选定的纯文本从 macOS 传到 Windows 剪贴板，再由你在允许粘贴的应用中手动粘贴。

这是一个独立的通用文本传输工具，不生成答案、不识别题目，也不定位或操作考试答题框。项目与任何考试机构、软件厂商均无隶属、认证或合作关系。仓库地址沿用早期名称，仅为保持链接有效。

[English](#english) · [使用边界与许可](./USE_POLICY.md) · [数据处理说明](./PRIVACY.md) · [版本变化](./CHANGELOG.md)

## 功能

- **手动发送**：Mac 端经本次确认后读取一次剪贴板；无后台持续监听。
- **手动接收**：Windows 端显式加载共享文件，查看字数，需要时展开预览，再点击复制到剪贴板。
- **普通粘贴**：在目标应用允许粘贴的地方自行使用粘贴命令。工具不寻找窗口、不模拟按键、不清空第三方编辑器。
- **短时共享**：共享快照有效期为 120 秒，过期后接收端拒绝使用。发送进程正常运行或正常退出时尝试清理本次文件。
- **标准库实现**：无需安装第三方 Python 包；启动器不自动下载依赖。

共享文件是明文，系统剪贴板也可能被其他程序、历史记录或云同步访问。只传输你有权分享的非敏感文本；完整数据流及删除限制见 [PRIVACY.md](./PRIVACY.md)。

## 快速开始

需要 macOS、Windows、Python 3（包含 Tkinter），以及双方可读写的同一个共享文件夹。Mac 导出使用硬链接原子发布，因此该目录的文件系统需支持硬链接；建议使用 Mac 本地目录，再通过虚拟机共享给 Windows。请使用自己控制的专用文件夹，避免云备份或广泛共享的目录。项目不负责配置虚拟机或网络共享。

### 1. 获取项目

```sh
git clone https://github.com/commingling/ruankao-clipboard-bridge.git
cd ruankao-clipboard-bridge
```

### 2. 在 Mac 上发送一次

先复制一小段无敏感内容的测试文字，然后运行：

```sh
bash mac/start_mac.sh
```

按提示确认后，程序才读取剪贴板，并在项目根目录生成 `.clipboard-bridge.json`。保留终端运行，在 120 秒内接收；到期或正常中断会尝试删除本次快照。

可以指定其他共享文件路径：

```sh
bash mac/start_mac.sh --file /path/to/shared/.clipboard-bridge.json
```

Mac 端路径也可通过 `CLIPBOARD_BRIDGE_FILE` 环境变量设置。两端必须选择同一实际文件；Mac 与 Windows 对该文件的路径写法通常不同。

### 3. 在 Windows 上接收

在共享项目目录中双击 `windows/start_win.bat`。如果项目拷贝到了另一处，在界面中选择 Mac 刚刚生成的共享文件，或运行：

```powershell
python windows/ruankao_paste_assistant.py --file "Z:\shared\.clipboard-bridge.json"
```

手动加载文件，确认你有权使用文本且目标应用允许粘贴，然后点击复制到 Windows 剪贴板。最后切换到自己的文本编辑器等应用，手动粘贴。

接收端拒绝过期、格式不符及超大内容，并检测读取期间或加载后的文件变更。文件不提供发送方身份认证，无法识别首次加载前的替换，请使用可信共享目录。正文上限为 1 MiB（按 UTF-8 字节计），完整文件上限为 2 MiB。请保持两端系统时间准确。

### 4. 结束与残留处理

正常导出会在 120 秒后尝试删除本次文件。异常退出、断电、文件权限变化可能留下文件；确认不再需要后，在 Mac 执行：

```sh
bash mac/start_mac.sh --clear
# 使用自定义路径时：
bash mac/start_mac.sh --file /path/to/shared/.clipboard-bridge.json --clear
```

如果导出提示目标已存在，先核对它是否为不再需要的本工具快照，再清理后重试。异常中断还可能留下同目录的 `.clipboard-bridge-<随机值>.tmp` 明文临时文件；`--clear` 只处理指定的 JSON 快照，临时文件需在停止导出后核对并手动删除。删除共享文件不会清除已经复制到 Windows 的内容、剪贴板历史或外部备份。

## 使用范围

适用于你拥有或获授权的文本，以及允许复制粘贴的个人笔记、普通编辑器和开发测试环境。使用前遵守目标软件的许可和操作规则。

本项目不提供考试作答、自动提交、规避监考、解除禁用粘贴或绕过访问限制的功能和适配支持。普通复制粘贴是否允许，应由具体环境和规则决定，不能仅凭工具名称判断。

源码使用标准 [MIT License](./LICENSE)。使用说明与维护者支持范围不改写 MIT，也不构成对第三方软件、内容或标识的授权。任何许可证或免责声明均不能保证免除依法应承担的责任。

## 从旧版迁移

本次调整移除了针对特定考试客户端的控件定位、自动粘贴及覆盖操作。原有脚本文件名暂时保留，但行为已变为通用手动传输。旧的 `.mac_clipboard.txt` 不再被读取。

升级前先停止旧的 Mac 监听进程和 Windows 助手。自行检查并清理旧共享目录中的 `.mac_clipboard.txt`，避免旧进程继续运行。新的快照过期机制不会清理旧版文件，也不会删除已经公开的历史提交或他人的副本。

## English

Clipboard Bridge transfers a text snapshot from macOS to the Windows clipboard through a shared file. Confirm each export on the Mac, explicitly load it on Windows, then copy and paste manually into an application that permits it.

The current version has no exam-window detection, answer generation, simulated keystrokes, automatic editor replacement, or continuous clipboard monitoring. The repository URL and script filenames are retained for continuity. This independent project has no affiliation with examination bodies or software vendors.

Snapshots are plaintext, expire after 120 seconds, and are removed on a best-effort basis by the sending process. Expiration is an application check, not encryption or secure erasure. Copied text can remain in the operating system clipboard, clipboard history, or backups. Use a trusted shared folder and non-sensitive text you are authorized to transfer.

Run `bash mac/start_mac.sh` on macOS and `windows/start_win.bat` on Windows. Both must refer to the same shared `.clipboard-bridge.json` file; use `--file` to select a different path. Python with Tkinter is required; no third-party Python packages are needed. The export directory must support hard links; a local Mac folder shared with the VM is recommended.

The source code remains under the standard MIT License. Project support boundaries do not add restrictions to that license, authorize third-party content, or override applicable law.
