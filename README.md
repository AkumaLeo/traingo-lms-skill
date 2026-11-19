# Traingo 自动学习与课件导出 Skill

把“真实浏览器学习监控 → 自动切章节 → 导出原始 PDF → 校验页数”的工作流打包成可分享的 [Hermes Agent](https://github.com/NousResearch/hermes-agent) Skill。

**不是刷课接口，也不代考。** 只操作用户有权访问、平台允许自动化的课程；不修改学习进度，不绕过身份验证或访问控制。

## 能做什么

- 检查指定在线课程与章节，区分课程、考试和项目总进度。
- 复用自己的 Chrome 登录态，每 30 秒检查进度/倒计时，完成后切换下一节。
- 在显式允许时处理已确认的普通继续学习提示；遇到登录/身份校验、并发冲突和未知弹窗停止。
- 优先导出当前文档的原始 PDF，通过权威页数和 PDF 文件解析核验，不把几张虚拟缩略图当作完整课件。
- 原子状态文件、重复运行锁、运行上限、停滞检测、逐课程完成记录。
- 默认只读预检，真正学习操作需要明确开启执行模式。

当前适配 Traingo 网页及其 Vue 3 `Photo` 文档查看器。**其他平台、不同页面版本或全画布课件没有自动兼容保证。**

## 安装到 Hermes

```bash
git clone https://github.com/AkumaLeo/traingo-lms-skill.git \
  "${HERMES_HOME:-$HOME/.hermes}/skills/traingo-lms"
```

目录已经存在时先比较版本，不要覆盖个人配置。然后在新会话中使用：

```bash
hermes -s traingo-lms
```

也可以把仓库下载后作为普通 Agent Skill 使用：入口是根目录 `SKILL.md`，关联脚本位于 `scripts/`。

**不会替换已有的 `lms-content-extraction` Skill，不会修改你的 Hermes 配置、定时任务或其他 Profile。**

## 依赖

- Python 3.9+。
- Chrome + OpenCLI 2.x + Browser Bridge 扩展；需要能够控制你自己的已登录标签。
- PyMuPDF，用于真正打开 PDF、校验页数。

在仓库目录创建独立环境：

```bash
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

OpenCLI 的安装与扩展配置以[上游说明](https://github.com/jackwener/opencli)为准。不要把未经验证的远程脚本直接管道到 Shell。

## 开始使用

1. 在自己的 Chrome 中打开培训平台并登录，进入准确的课程页面。登录、验证码、MFA 或身份核验由本人完成。
2. 把目标标签设为当前标签，按本机 OpenCLI 帮助完成绑定：

```bash
opencli browser bind --session lms-study
opencli browser state --session lms-study
```

3. 在 Hermes 中说：

> 使用 traingo-lms：先导出这门课程全部文档并校验页数，再从最早未完成章节开始学习，每30秒监控；跳过考试，异常立即报告。

或只说：

> 使用 traingo-lms：只提取当前课程文档，不启动自动学习。

4. 手动使用脚本时，先查看当前版本的精确参数，并复制 `examples/` 下配置到**仓库外**：

```bash
python scripts/traingo_watch.py --help
python scripts/extract_course.py --help
```

不要直接使用示例占位课程启动。提供你自己的课程标题、允许的站点/课程路径、浏览器会话和输出目录。

### 两个功能分别验收

导出成功不等于在线完课；监控进程启动不等于学习仍在计时。至少三次观测、跨越两个轮询间隔，确认实际进度或倒计时变化后才算启动验证通过。最终核对真实逐章100%证据并记录逐课程完成清单；清单不保存历史逐章快照，不能把考试或整个项目误报完成。

脚本导出当前单份文档；代理负责按目录逐章调用、保存安全清单、核对数量并返回最早未完成章。若平台变版或页面类型不符，应停止修正适配，不能猜测完成。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试夹具是明确构造的本地页面/快照，不是企业培训平台的实时数据。测试覆盖的行为及复现步骤见 [验证说明](references/verification.md)。通过单元测试不代表任意帐号、浏览器或课程版本已真实跑通。

## 隐私与限制

- 不发布学员工号、姓名、邮箱、培训文件、私人课程 ID、签名下载链接或浏览器状态。
- 不导出 Cookie、令牌、密码，不读取浏览器凭据数据库。
- PDF 下载使用当前浏览器授权上下文；访问被拒绝/CORS阻止时不绕过，改用官方导出或人工下载。
- 不破解 DRM，不直接调用课程计时/完成上报 API，不自动完成考试、问卷、测验或身份确认。
- 输出可能是公司内部课件，请自行确认本地保存和转发权限。**开源代码不授予课件的再分发许可。**
- 当前未内置自动发送微信/飞书，也不自动安装后台服务；由调用 Skill 的代理按用户授权安排通知与持续运行。
- 电脑休眠、标签被关闭、会话过期会影响任务；须通过状态文件和真实页面核对，不要只看进程还在。

详细说明：[导出](references/export.md) · [隐私](PRIVACY.md) · [安全报告](SECURITY.md)

## License

MIT，仅适用于本仓库代码和原创文档；培训资料及第三方工具各自遵守其许可。
