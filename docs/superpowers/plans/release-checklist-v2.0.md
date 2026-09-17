# v2.0 发布检查单（用户执行）

> 基线：分支 `feat/v2.0`；手机端 debug APK 已做过真机与 headless 验证（记录见 A 节）。
> 本清单所有发布动作（push / Release / gitee 同步）均为用户确认制，agent 不代为执行。

## A. 真机验收记录（发布前置）

- [x] vivo 校园网扫描 —— ✅ **2026-09-17 重测通过**（真实网络列表正常，DrCOM 认证正常）
- [ ] vivo 一键连接重测 —— 【待用户确认】（用最新 retest APK 走一遍首次连接 → 系统弹窗 → 连接成功）
- [ ] PC 端手动测试（扫描 + 已保存网络连接）—— 【待用户确认】
- [ ] Android ≤12 设备回归 —— 【未测】（无设备；连接路径的 API 29 / 28- 分支未经真机覆盖；若有低版本设备建议补测）

## B. 发布动作（按序执行）

- [ ] 全部真机验收通过（上方 A 节勾满 + Plan 1 Task 8 / Plan 2 Task 2 Step 4 清单勾满）
- [ ] Android Studio 出签名 release APK（Build → Generate Signed Bundle/APK，沿用现有 keystore）
- [ ] 安装签名包复测一遍首页 + WiFi 一键连接（确认签名包与 debug 行为一致）
- [ ] 确认推送：`git push origin feat/v2.0`（经用户确认后执行；可 GitHub 直接合并 main 或开 PR）
- [ ] GitHub Release：tag `v2.0`，附件 `AUST校园认证助手.apk`（签名版），描述用 README 的 v2.0 段 + 下方 D 节补充
- [ ] gitee 镜像同步（`gitee push`），Release 附件同步（沿用 v1.x 的发布方式）
- [ ] README 中新增 APK 下载链接（指向新 Release）

## C. LEDGER 分诊（deferred minors）

发布前对照 `.superpowers/sdd/progress.md`（本地 SDD ledger，不入库）里的 deferred minors，逐类勾选确认「随 v2.0 发布即可 / 需要修」：

- [ ] 连接类：waitConnected 在「已连其他 WiFi 的 redacting 设备」上可能误报；WPA2-only 凭据写入；目标编辑器与扫描并发时 no-op（30s 自愈）
- [ ] 链接/导航类：单级撤销（后续 snackbar 会顶掉 undo）、恢复分类落在列表尾部、空分类不可作拖拽目标
- [ ] 布局类：设备列表 3 行可见 + 常驻滚动条为精确适配，其他 DPI 可能零间隙
- [ ] 工具类：targets 存储值非数组时回落 `[]` 而非默认值；添加失败回滚会清空已输入关键字
- [ ] 全部判为可发布（或已修）→ 勾选；否则记录到 issue 并注明版本

## D. Release 说明补充（写进 GitHub/gitee Release 描述）

- [ ] 本地保存的密码**仅存本机**：`allowBackup=false`，不参与云备份 / 换机迁移（卸载即丢失，需重填）
- [ ] WiFi 连接三档机制（随 Android 版本自动选择）：
  - Android 11+：走系统「添加网络」对话框，用户确认一次后系统接管重连
  - Android 10：以系统 WiFi 建议（suggestion）形式添加，需在通知/设置中批准
  - Android 9-：直接写入系统网络配置并连接
- [ ] **WPA2-only 限制**：一键连接仅支持 WPA2 个人版（AUST 校园网即 WPA2）；企业级（WPA-Enterprise）暂不支持
- [ ] 检测/扫描权限说明：Android 13+ 申请「附近的设备」权限，且所有版本都需要「位置」权限（国产 ROM 如 vivo/小米 在 13+ 上仍强制要求位置权限与系统定位开关，这是已知的 Android 生态现实）；首次连接经系统确认（Android 11+ 为系统「添加网络」弹窗）

## 备注

- APK 名称：`AUST校园认证助手.apk`；keystore 位置与口令按 v1.x 发布时约定，勿写入仓库
- 发布后回填：GitHub/gitee Release 链接 → README 下载区
