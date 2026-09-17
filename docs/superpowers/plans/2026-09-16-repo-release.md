# AUST v2.0 收尾与发布实施计划（Plan 3/3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收尾发布准备：版本号升到 v2.0、README 更新、仓库卫生检查；产出可供用户签名发布的最终状态（push 与 Release 上传由用户确认后执行）。

**Architecture:** 纯仓库工程工作，无新代码。手机端发布链：本地 debug 验收（Plan 1/2 已做）→ 版本号落定 → 用户 Android Studio 出签名 APK → GitHub Release + gitee 镜像同步。

**Tech Stack:** git、Gradle（versionName 修改）、gh CLI（用户确认后推送）。

## Global Constraints

- 分支 `feat/v2.0`；工作目录 `F:\kakuns开源项目\AUST`
- 所有对外发布动作（git push、Release 上传、gitee 同步）**必须先经用户确认**，本计划只准备到"等待发布"状态
- 手机端 versionName `2.0` / versionCode `2`；PC 端 v1.3

## Amendment 2026-09-17（终审遗留清单 → 显式任务）

以下为终审 + 各任务评审累积的发布前必做项，已并入下方任务步骤：

1. `package.json` version `1.2.0` → `2.0`（Task 1）
2. 删除 `phone/android/app/src/androidTest/java/com/getcapacitor/myapp/ExampleInstrumentedTest.java`（断言错误包名 `com.getcapacitor.app`，模板遗留；Task 1）
3. `git update-index --chmod=+x phone/android/gradlew`（Task 1）
4. 根 `.gitignore` 增加 `__pycache__/`、`*.pyc`（Task 3）
5. 更新 `phone/打包部署指南.md`：删除「npx cap add android」全流程叙述，改为 clone 后 `npm install → npx cap sync android → gradlew assembleDebug`；补充 Gradle 8.7 / JBR 21 / `android.overridePathCheck`（中文路径）/ 腾讯镜像说明（Task 2）
6. 提交 `phone/tools/test-pure.mjs`（pure-function node 测试：normalizeUrl/escHtml/ensureSections 等）+ `phone/tools/CDP-SMOKE.md`（headless Edge 冒烟配方），供后续贡献者复跑（Task 3）
7. 发布检查单追加：a) vivo 重测通过记录；b) LEDGER（`.superpowers/sdd/progress.md`）中 deferred minors 分诊勾选；c) Release 说明中注明「本地保存的密码不参与云备份（allowBackup=false）」与 WPA2-only 限制（Task 3）


---

### Task 1: 版本号落定 + 构建产物复核

**Files:**
- Modify: `phone/android/app/build.gradle`（versionCode/versionName）
- Modify: `phone/www/index.html`（如 appbar 版本字样未更新为 v2.0）

**Interfaces:**
- Produces: 最终 debug APK（供 Task 2 的 README/Release 描述引用版本号）

- [ ] **Step 1: 修改版本号**

`phone/android/app/build.gradle` 中：

```groovy
versionCode 2
versionName "2.0"
```

（当前为 `versionCode 1` / `versionName "1.0"`）

- [ ] **Step 2: 复核 index.html 版本字样**

```bash
grep -n "v2.0\|v1.3\|v1.2" phone/www/index.html | head -5
```

Expected: 标题/appbar 显示 v2.0（Plan 1 Task 3 已改）；若残留 v1.x 字样则改掉。

- [ ] **Step 3: 最终构建**

```bash
cd "F:/kakuns开源项目/AUST/phone" && npx cap sync android && cd android && JAVA_HOME="D:/AndroidStudio/jbr" ./gradlew assembleDebug
```

Expected: `BUILD SUCCESSFUL`；APK 时间戳为最新。

- [ ] **Step 4: Commit**

```bash
git add phone/android/app/build.gradle phone/www/index.html
git commit -m "release(phone): bump version to 2.0 (versionCode 2)"
```

---

### Task 2: README 更新

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 手机端 v2.0 功能清单（spec §1-§5）、`phone/打包部署指南.md` 路径

- [ ] **Step 1: 更新 README**

在现有结构上增量修改（不重写全文）：

1. "更新使用说明"追加：

```markdown
v2.0 — Pocket 全新改版
- 全新扁平化界面（类 Twitter 风格），深色模式全量适配，内嵌 Inter 字体
- 新增 WiFi 扫描与一键连接（首次连接需系统确认一次，之后自动重连）
- 修复常用链接：链接格式校验、删除确认/撤销、分类清空不再消失（可恢复默认）
- 手机端源码已开源于本仓库 `phone/` 目录（Capacitor + Android 工程）
```

2. "前瞻"上方追加"源码构建"段：

```markdown
#### 手机端源码构建

源码位于 `phone/`，构建步骤见 `phone/打包部署指南.md`（Node 18+ / Android Studio / JDK 17）。
```

3. 已知问题段：删除已修复的"自助系统加载获取有问题"条目（保留仍未解决项时注明状态）。

- [ ] **Step 2: 本地预览 README（可选）**

`gh api` 不必要；直接目视检查 Markdown 结构无断裂。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README — v2.0 release notes and phone source section"
```

---

### Task 3: 仓库卫生 + 发布检查单

**Files:**
- Verify: `.gitignore`（根与 phone/）
- Verify: `docs/design/`、`docs/superpowers/`（spec + 3 个 plan 已入）

- [ ] **Step 1: 卫生检查**

```bash
cd "F:/kakuns开源项目/AUST"
git status --short                       # 预期：干净
git ls-files phone | grep -cE "node_modules|build/|\.apk$|local.properties|assets/public" || echo "0 (clean)"
du -sh phone --exclude=node_modules --exclude=build 2>/dev/null | head -1
```

Expected: 构建产物零入库；`phone/` 源码体积应在 5MB 以内（android 工程 + www + 工具）。

- [ ] **Step 2: 生成发布检查单（写入 docs/superpowers/plans/release-checklist-v2.0.md）**

```markdown
# v2.0 发布检查单（用户执行）

- [ ] 真机验收通过（Plan 1 Task 8 / Plan 2 Task 2 Step 4 全部勾选）
- [ ] Android Studio 出签名 release APK（Build → Generate Signed Bundle/APK，沿用现有 keystore）
- [ ] 安装签名包复测一遍首页 + WiFi 一键连接（签名包与 debug 行为一致）
- [ ] 确认推送：`git push origin feat/v2.0`（经用户确认后执行；可在 GitHub 上直接合并到 main 或开 PR）
- [ ] GitHub Release：tag `v2.0`，附件 `AUST校园认证助手.apk`（签名版），描述用 README 的 v2.0 段
- [ ] gitee 镜像同步（`gitee push`），Release 附件同步（沿用 v1.x 的发布方式）
- [ ] README 中新增 APK 下载链接（指向新 Release）
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers
git commit -m "docs: v2.0 release checklist"
```

- [ ] **Step 4: 向用户汇报待发布状态**

汇报内容：分支、最后一个 commit、debug APK 路径、检查单路径、需要用户执行的 4 个动作（验收 / 签名出包 / 确认 push / Release 上传）。**不执行任何 push**。

---

## Self-Review 记录

- 覆盖检查：spec §6（仓库结构 Task 2、版本 Task 1、构建流程全局）、§7 验收（在 Plan 1/2 任务内 + 本计划检查单）；发布动作全部为用户确认制，符合 CLAUDE.md"未确认不推送"
- 无代码任务，无类型一致性问题；检查单与 Plan 1/2 的验收步骤一一引用（无重复描述细节，避免漂移）
