# 豆包 Work：从 GitHub 部署到本机

本适配保留原有 Hermes 工作流，也可供其他能读 Agent Skill 的宿主使用。它提供**可执行的本地依赖引导和离线冒烟检查**，不是豆包插件、MCP 服务或自动注册接口。

## 给豆包 Work 的一句话

> 请把 https://github.com/AkumaLeo/traingo-lms-skill 部署到我授权的本机目录：先用你实际可用的 GitHub/下载及文件工具取得并检查仓库，阅读 README.md、SKILL.md、docs/DOUBAO.md、scripts/bootstrap.py 和 requirements.txt 后按文档先做只读预检，再用 --install 建立仓库独立环境并用 --check 验收；不要覆盖已有目录、安装全局软件或浏览器扩展，不要绑定浏览器、登录、启动学习、考试或绕过验证，技能上传/启用如需界面操作请明确交给我，最后分级报告实际完成项和缺失项，不要把下载或依赖就绪说成技能已启用。

这一句话是**工作指令**，不是保证豆包具有任意本地工具权限。下载、创建 `.venv` 和 pip 联网安装均限定于授权的本机目录；若宿主需要额外确认，先取得确认。不执行仓库未检查的命令。若只有云端沙箱或不能访问本机文件/终端，必须说明“尚未部署到本机”，提供下面的人工步骤，不能把云端安装描述成本机 Chrome 已可用。

## 取得代码与检查

1. 用宿主实际提供的 GitHub、下载或终端工具取得上述公开仓库。已有 Git 时可执行：

   ```text
   git clone https://github.com/AkumaLeo/traingo-lms-skill.git
   cd traingo-lms-skill
   ```

   没有 Git 时可从 GitHub 页面下载 ZIP 并解压到新的本机文件夹。不猜宿主工具名、不运行远程一键安装脚本；目录存在时先检查，不覆盖、不自动删除、不 `git reset --hard`。
2. **执行前**用文件工具阅读 README、SKILL、本文、bootstrap 脚本和 requirements。核对来源与差异；不要读取密码、Cookie、认证存储或其他用户文件。
3. 检查本机是否允许运行 Python、Node.js、npm、OpenCLI，以及能否使用本人的 Chrome。缺失项由用户按官方说明安装；不要自动全局 npm/pip 安装、安装扩展、改系统设置或创建后台服务。

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

### 脚本实际做什么

- 仅用 Python 标准库。默认不创建目录、不安装包、不写报告、不连接课程或浏览器。
- 检查正在运行的 Python ≥3.9，通过 `shutil.which` 查找 `node`、`npm`、`opencli`，仅执行有超时的 `--version`。成功只证明这些命令响应，不证明 OpenCLI 2.x 兼容性或扩展已连接；请人工核对本机版本及[上游说明](https://github.com/jackwener/opencli)。
- `--install` 是唯一安装入口：只在仓库 `.venv` 安装现有 `requirements.txt`。pip 使用隔离配置、禁用缓存及版本检查，无全局安装、无 sudo。仅这一步可能联网；不会自动安装 Node/npm/OpenCLI/Chrome/扩展。
- `.venv` 带引导器所有权标记；已有未知目录、符号链接或创建失败的半成品一律停止，不接管、不清理。人工检查后改用新仓库副本，或自行备份/移动原环境。重复 `--install` 可复用本引导器创建的环境，pip 再次核对依赖；不会清空环境或覆盖项目配置。它不是锁版本的可复现构建，requirements 允许范围内的解析结果可随时间变化。
- 验证本地 venv 的 Python 版本、环境身份及 PyMuPDF 版本范围。`--check` 仅在依赖验证通过后，用该 venv Python 运行 `extract_course.py --help` 和 `traingo_watch.py --help`，不加载课程配置、不绑定标签、不执行页面命令，也不开始学习。无需自动建立 MCP。
- 所有子进程 `shell=False`、关闭标准输入、设超时：探测/帮助每项 15 秒，初次本地 ensurepip 120 秒，显式 pip 安装 300 秒。禁用 pip 配置及 netrc 认证读取。pip 超时/失败可能留下部分依赖；修复网络或 Python 兼容性后显式重试，再运行 `--check`。
- 输出只包含固定状态、工具名、脚本名和修复建议，不转发子进程 stdout/stderr、异常详情、绝对路径、环境变量或版本原文。失败时不应为“诊断”读取认证存储或上传原始 pip/浏览器日志。脚本不写报告；如人工保存摘要，请留本机并在分享前检查隐私。`.venv/` 已由 `.gitignore` 排除，不要上传它。

退出码 `0` 表示本次所选检查全部通过；`1` 表示缺失项或失败，`2` 为参数错误。**默认检查即使返回 0，也没有执行 `--check`，更没有注册技能。** `--install --check` 返回 0 也只达到下述第 3 级。

## 上传技能的明确边界

[豆包 Work 官方技能说明](https://www.doubao.com/work/docs/zh-cn/articles/081010973544)支持上传包含 `SKILL.md` 的技能文件/文件夹，并使用 YAML 中的 `name`、`description`。本仓库根目录已有这两个字段；上传时保留 `scripts/`、`references/`、`docs/` 等相对路径，不只复制 SKILL 正文，也不上传 `.venv`、Git 元数据、个人配置、课程内容或会话数据。

按当前豆包界面人工选择上传/启用；界面具体入口以官方说明及本机实际界面为准。**本文不声称存在自动技能注册 API、自动发现目录或“复制到固定路径即启用”的约定。** 若豆包工具不能完成这一步，应停在“依赖就绪、待人工上传/启用”，不能编造已安装。

[官方插件说明](https://www.doubao.com/work/docs/zh-cn/articles/705018132598)提到本地 STDIO MCP，但此 Skill 不需要 MCP，也没有为部署额外启动服务。上传后的脚本实际执行位置、是否能访问本机目录/Chrome，要在当前宿主权限内单独核对；不能把文件上传成功等同于本机执行可用。

## 验收等级：只报告有证据的那一级

| 等级 | 必须有的证据 | 不代表什么 |
| --- | --- | --- |
| 1 代码已取得 | 本机新目录中实际文件已读、来源已检查 | 不代表依赖已安装 |
| 2 本地依赖就绪 | 引导器验证 owned `.venv`、Python、PyMuPDF；逐项列出工具缺失/探测结果 | 不代表技能已启用、扩展已连接 |
| 3 离线冒烟通过 | `--check` 两个脚本分别 `help_ok` 且 `smoke_passed`；同时记录退出码和工具缺失项 | 不代表豆包已注册或真实课程跑通 |
| 4 宿主技能已启用 | 用户/实际宿主界面核对上传和启用，并能读取技能及关联文件 | 不代表可以控制本机浏览器 |
| 5 真实环境验证 | 用户另行授权后，人工准备 Chrome/扩展与登录，按 README/SKILL 核对目标页和只读结果 | 不代表已开始学习、已完课或考试完成 |

部署到第 3/4 级即可结束本任务。示例汇报格式：“已取得代码；本地依赖已验证；两项 help 冒烟通过/失败；工具缺失：……；技能上传/启用：待人工确认；未绑定浏览器、未学习。”不可没有执行证据就照抄成功句子。

**部署授权不等于学习授权。** 不自动运行监控/学习、不打开课程、不自动答题或提交考试/问卷；不代登录、不处理验证码/MFA/人脸核验，不绕过访问控制或反自动化机制。后续真实课程任务必须重新确认范围与平台规则，严格遵守 [SKILL.md](../SKILL.md) 的原有安全边界。

## 离线测试

```text
python -m unittest discover -s tests -v
```

引导器测试使用 unittest mocks，不运行真实 pip、浏览器或网络；包含默认只读、显式安装、重复运行、未知环境保护、失败/超时隐私、venv help 冒烟和 Windows 路径布局。原有 JS 测试依赖本机 Node；PDF 校验测试需要 PyMuPDF。离线测试通过不证明豆包端上传/权限或 Windows 实机已验证。
