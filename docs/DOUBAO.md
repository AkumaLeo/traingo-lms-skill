# 豆包 Work：从 GitHub 部署到本机

本适配保留原有 Hermes 工作流，也可供其他能读 Agent Skill 的宿主使用。它提供**可执行的本地依赖引导和离线冒烟检查**，不是豆包插件、MCP 服务或自动注册接口。

## 给豆包 Work 的一句话

> 请检查并按 https://github.com/AkumaLeo/traingo-lms-skill 的 README、SKILL 和 docs/DOUBAO.md 部署到我授权的本机新目录：先只读预检，获准后 --install --check；联网受限时经我明确同意才用文档的 HTTPS 镜像参数；不覆盖、不全局安装、不绑定浏览器、不登录或学习，上传/启用需我操作时交给我，按实际退出码和证据报告，不把沙箱当本机或部分 help 成功当完整通过。

这一句话是**工作指令**，不是保证豆包具有任意本地工具权限。下载、创建 `.venv` 和 pip 联网安装均限定于授权的本机目录；若宿主需要额外确认，先取得确认。不执行仓库未检查的命令。若只有云端沙箱或不能访问本机文件/终端，必须说明“尚未部署到本机”，提供下面的人工步骤，不能把云端安装描述成本机 Chrome 已可用。

## 本机还是沙箱：先确认执行位置

记录执行器实际的 OS、解释器和仓库位置，并由宿主能力/用户确认能否访问授权的本机目录；不要读取认证存储。`sandbox_runtime` 等路径是隔离执行的线索，不足以独自证明是物理 PC 或远端云。沙箱中的 PATH 找不到 Chrome/OpenCLI，只说明**当前执行环境**未发现，不能断言用户 PC 没有 Chrome。localhost 是执行命令的那个环境，不天然指向用户电脑；本机浏览器是否可达须另行授权后验证，部署阶段不启动连接探测。

## 取得代码与检查

1. 用宿主实际提供的 GitHub、下载或终端工具取得上述公开仓库。已有 Git 时可执行：

   ```text
   git clone https://github.com/AkumaLeo/traingo-lms-skill.git
   cd traingo-lms-skill
   ```

   没有 Git 时可从 GitHub 页面下载 ZIP 并解压到新的本机文件夹。不猜宿主工具名、不运行远程一键安装脚本；目录存在时先检查，不覆盖、不自动删除、不 `git reset --hard`。
2. **执行前**用文件工具阅读 README、SKILL、本文、bootstrap 脚本和 requirements。核对来源与差异；不要读取密码、Cookie、认证存储或其他用户文件。
3. 检查本机是否允许运行 Python、Node.js、npm、OpenCLI，以及能否使用本人实际使用的浏览器（如 Edge）。缺失项由用户按官方说明安装；不要自动全局 npm/pip 安装、安装扩展、改系统设置或创建后台服务。

## 引导命令

所有命令均在仓库根目录执行，不需要管理员权限，也不需要激活虚拟环境。

### macOS / Linux

```bash
python3 scripts/bootstrap.py
# 阅读预检结果后，明确允许建立本地环境与 pip 联网安装：
python3 scripts/bootstrap.py --install
python3 scripts/bootstrap.py --check
# 也可把后两步合并：python3 scripts/bootstrap.py --install --check
```

### Windows PowerShell

```powershell
py -3 scripts/bootstrap.py
py -3 scripts/bootstrap.py --install
py -3 scripts/bootstrap.py --check
# 或：py -3 scripts/bootstrap.py --install --check
```

`py` 不存在时，使用已确认版本为 3.9+ 的 `python`；不要猜系统中命令指向的版本。不需要更改 PowerShell 执行策略。

### 显式选择 pip 镜像（可选）

默认仍使用 pip 默认索引；不会读取用户 pip 配置或自动切源。公共 PyPI 无法访问时，先确认本次网络访问和第三方镜像由你授权，再显式指定，例如[清华 TUNA 的 PyPI 镜像](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)：

```powershell
py -3 scripts/bootstrap.py --install --check --index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

macOS/Linux 将 `py -3` 换成已确认的 `python3`。`--index-url` 必须与 `--install` 同用，仅接受 HTTPS，拒绝用户名/密码、查询、片段、空白和控制字符；仍使用隔离 pip，不关闭 TLS、不添加 trusted-host。URL 不回显，但人工输入可能留在终端历史，请勿输入私密索引或凭据。示例不保证当前网络可达，也不是锁定包版本/供应链担保；选择镜像即信任其包来源。不要用非隔离安装或改全局 pip 配置来绕过检查。

### 脚本实际做什么

- 仅用 Python 标准库。默认不创建目录、不安装包、不写报告、不连接课程或浏览器。
- 检查正在运行的 Python ≥3.9，通过 `shutil.which` 查找 `node`、`npm`、`opencli`，仅执行有超时的 `--version`。成功只证明这些命令响应，不证明 OpenCLI 2.x 兼容性或扩展已连接；请人工核对本机版本及[上游说明](https://github.com/jackwener/opencli)。
- Windows npm 的 `opencli.cmd` / `npm.cmd` 不交给 shell 或 cmd.exe：共享 argv 构造器只检查 shim 同目录的预期 `node_modules/@jackwener/opencli` / `node_modules/npm` 及 package.json 的名称、bin 元数据，校验入口真实路径位于包内，再以同目录或 PATH 的 `node.exe` 直接启动 JS。npm 仅接受 `bin/npm-cli.js`。不解析/执行 .cmd 内容；未知布局明确失败，按官方安装说明人工修复。元数据检查不是包签名认证；PATH、安装目录和依赖来源应由本人信任。原生可执行文件、POSIX 可执行脚本仍正常使用。
- `--install` 是唯一安装入口：只在仓库 `.venv` 安装现有 `requirements.txt`。pip 使用隔离配置、禁用缓存及版本检查，无全局安装、无 sudo。仅这一步可能联网；不会自动安装 Node/npm/OpenCLI/Chrome/扩展。
- `.venv` 带引导器所有权标记；已有未知目录、符号链接或创建失败的半成品一律停止，不接管、不清理。人工检查后改用新仓库副本，或自行备份/移动原环境。重复 `--install` 可复用本引导器创建的环境，pip 再次核对依赖；不会清空环境或覆盖项目配置。它不是锁版本的可复现构建，requirements 允许范围内的解析结果可随时间变化。
- 验证本地 venv 的 Python 版本、环境身份及 PyMuPDF 版本范围。`--check` 仅在依赖验证通过后，用该 venv Python 运行 `extract_course.py --help` 和 `traingo_watch.py --help`，不加载课程配置、不绑定标签、不执行页面命令，也不开始学习。无需自动建立 MCP。
- 所有子进程 `shell=False`、关闭标准输入、设超时：探测/帮助每项 15 秒，初次本地 ensurepip 120 秒，显式 pip 安装 300 秒。禁用 pip 配置及 netrc 认证读取。pip 超时/失败可能留下部分依赖；修复网络或 Python 兼容性后显式重试，再运行 `--check`。
- 输出只包含固定状态、工具名、脚本名和修复建议，不转发子进程 stdout/stderr、异常详情、绝对路径、环境变量或版本原文。失败时不应为“诊断”读取认证存储或上传原始 pip/浏览器日志。脚本不写报告；如人工保存摘要，请留本机并在分享前检查隐私。`.venv/` 已由 `.gitignore` 排除，不要上传它。

**只有整个 `--check` 退出码为 `0`（包括 node/npm/opencli 工具探测和依赖）才算完整通过。** 两个 `help_ok` 只代表脚本帮助可运行；工具缺失时输出 `partial_help_ok` 并返回 `1`，不能报完整通过。退出码 `0` 表示本次所选检查全部通过；`1` 表示缺失项或失败，`2` 为参数错误。**默认检查即使返回 0，也没有执行 `--check`，更没有注册技能。** `--install --check` 返回 0 也只达到下述第 3 级。

## 上传技能的明确边界

[豆包 Work 官方技能说明](https://www.doubao.com/work/docs/zh-cn/articles/081010973544)支持上传包含 `SKILL.md` 的技能文件/文件夹，并使用 YAML 中的 `name`、`description`。本仓库根目录已有这两个字段；上传时保留 `scripts/`、`references/`、`docs/` 等相对路径，不只复制 SKILL 正文，也不上传 `.venv`、Git 元数据、个人配置、课程内容或会话数据。

不支持或采用未经官方文档确认的 `.user_skills` 复制目录；不能把复制成功当作注册/启用证据。

按当前豆包界面人工选择上传/启用；界面具体入口以官方说明及本机实际界面为准。**本文不声称存在自动技能注册 API、自动发现目录或“复制到固定路径即启用”的约定。** 若豆包工具不能完成这一步，应停在“依赖就绪、待人工上传/启用”，不能编造已安装。

[官方插件说明](https://www.doubao.com/work/docs/zh-cn/articles/705018132598)提到本地 STDIO MCP，但此 Skill 不需要 MCP，也没有为部署额外启动服务。上传后的脚本实际执行位置、是否能访问本机目录/目标浏览器，要在当前宿主权限内单独核对；不能把文件上传成功等同于本机执行可用。

## Windows 使用 Microsoft Edge（独立的浏览器验收）

**不要求为了本 Skill 迁移到 Chrome。** Edge 基于 Chromium，但“同内核”不等于本机 Browser Bridge 已连接。本仓库只经 OpenCLI 的 session/profile 执行 DOM，不启动/发现某个品牌的浏览器、不读取 UA、不硬编码 Chrome 路径；Bridge 连接到正确的 Edge 配置上下文后，现有脚本可尝试使用，无需搬运登录态。

证据边界：检查过的 OpenCLI 2.0.2 本机 `--help`、`browser bind/state --help`、`profile --help` 仍把 profile 称为 Chrome profile/context；[上游 README](https://github.com/jackwener/opencli#2-install-the-browser-bridge-extension) 明确写 Chrome/Chromium，并提供 Chrome Web Store 和 release 扩展 ZIP，而非本仓库的 Edge 一键安装保证。未确认独立的官方 Edge Add-ons 商店条目，也未完成 Windows/Edge 实机连接测试。

用户另行授权浏览器准备后，按以下顺序人工验证；引导脚本不会执行这些步骤：

1. 在**实际运行命令的同一台 Windows/同一网络上下文**打开本人 Edge，不把沙箱的 localhost 当作本机。保留本人现有 Edge 登录，由本人处理登录/MFA；不复制密码、Cookie、浏览器目录、会话或认证存储到 Chrome/沙箱。
2. 先查看上游发布者和权限。[微软官方说明](https://support.microsoft.com/microsoft-edge/add-turn-off-or-remove-extensions-in-microsoft-edge-9c0ec68c-2fbc-2f2c-9ff0-bdc76f46b026)支持在 Edge 从 Chrome Web Store 安装扩展；可由本人在 Edge 打开[上游 OpenCLI 商店链接](https://chromewebstore.google.com/detail/opencli/ildkmabpimmkaediidaifkhjpohdnifk)，按界面确认“允许来自其他商店的扩展”和权限。或从[上游 Releases](https://github.com/jackwener/opencli/releases)取**构建好的**扩展 ZIP（不是源码 ZIP），本人依[微软侧载指南](https://learn.microsoft.com/en-us/microsoft-edge/extensions-chromium/getting-started/extension-sideloading)在 `edge://extensions` 开启开发人员模式并“加载解压缩的扩展”。两种方式均需本人明确同意；组织策略禁止时停止，不绕过、不降低浏览器/系统安全策略。
3. 人工确认扩展启用且能连接本地 Bridge；经授权再执行 `opencli doctor`、`opencli profile list`。输出可能含本机标签或配置资料，留本机，不上传原始日志。命令/扩展安装成功不等于已连接；看不到 Edge 对应 context 时停止，报告当前上游/版本/策略或网络边界，不假装已绑定，也不擅自更换浏览器或开调试端口。
4. 多配置/多浏览器共存时，只用实际返回并由本人确认的 Edge Bridge contextId/别名。对每条命令显式传 `--profile`，不运行 `profile use` 改共享默认值，不猜“Default”等磁盘目录名。本人将授权课程页放到该 Edge 配置的当前标签后，按本机帮助使用：

   ```powershell
   # 用 profile list 的真实结果替换此占位值，勿照抄：
   $BridgeProfile = '已确认的Edge上下文ID或别名'
   opencli --profile $BridgeProfile browser bind --session lms-study
   opencli --profile $BridgeProfile browser state --session lms-study
   ```

5. 核对**确切 URL、课程标题、章节标题/目录**，不是只看是否打开网页；若工具看到错误窗口、空白/登录页，先停止查绑定，不立即要求重复登录、不新开并发课程。提取脚本传同一 `--profile` 与 `--session`，监控的本地配置填同一 `profile`、`session` 和精确课程 title/URL 白名单；先只读探测，未通过不得启动学习。浏览器连接和平台 DOM 兼容性是两个独立验收门槛。

## 验收等级：只报告有证据的那一级

| 等级 | 必须有的证据 | 不代表什么 |
| --- | --- | --- |
| 1 代码已取得 | 本机新目录中实际文件已读、来源已检查 | 不代表依赖已安装 |
| 2 本地依赖就绪 | 引导器验证 owned `.venv`、Python、PyMuPDF；逐项列出工具缺失/探测结果 | 不代表技能已启用、扩展已连接 |
| 3 完整预检/离线冒烟通过 | `--check` 整体退出码为 0，工具及依赖全部通过，两个脚本分别 `help_ok` 且 `smoke_passed` | 不代表豆包已注册或真实课程跑通 |
| 4 宿主技能已启用 | 用户/实际宿主界面核对上传和启用，并能读取技能及关联文件 | 不代表可以控制本机浏览器 |
| 5 真实环境验证 | 用户另行授权后，人工准备目标浏览器/扩展与登录，按 README/SKILL 核对目标页和只读结果 | 不代表已开始学习、已完课或考试完成 |

部署到第 3/4 级即可结束本任务。示例汇报格式：“已取得代码；本地依赖已验证；两项 help 冒烟通过/失败；工具缺失：……；技能上传/启用：待人工确认；未绑定浏览器、未学习。”不可没有执行证据就照抄成功句子。

**部署授权不等于学习授权。** 不自动运行监控/学习、不打开课程、不自动答题或提交考试/问卷；不代登录、不处理验证码/MFA/人脸核验，不绕过访问控制或反自动化机制。后续真实课程任务必须重新确认范围与平台规则，严格遵守 [SKILL.md](../SKILL.md) 的原有安全边界。

## 离线测试

```text
python -m unittest discover -s tests -v
```

引导器测试使用 unittest mocks，不运行真实 pip、浏览器或网络；包含默认只读、显式安装、重复运行、未知环境保护、失败/超时隐私、venv help 冒烟和 Windows 路径布局。原有 JS 测试依赖本机 Node；PDF 校验测试需要 PyMuPDF。离线测试通过不证明豆包端上传/权限或 Windows 实机已验证。
