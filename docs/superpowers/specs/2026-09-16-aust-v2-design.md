# AUST 校园认证助手 v2.0 设计文档

日期：2026-09-16
状态：待评审
范围：手机端（Capacitor）UI 翻新 + WiFi 一键连接；PC 端新增 WiFi 功能；手机端源码并入 hanasite/AUST 仓库

---

## 1. 背景与目标

现状：

- PC 端：`school_auth_v1.0 ~ v1.2lite.py`（tkinter），功能稳定，UI 不动
- 手机端：Capacitor 6 WebView 壳 + 单文件 `www/index.html`（v1.2 Pocket / 开发版 v1.3），三个 Tab（认证/自助系统/常用链接）。视觉风格老气、动效粗糙；无 WiFi 相关能力
- 手机端源码只在本地 `F:\Android\aust-app`，未入库

本次目标：

1. **手机端 UI 翻新**：A1 扁平风格（Twitter 清新感）+ 内嵌 Inter 字体 + Lucide 线性图标库，替换全部 emoji
2. **新增 WiFi 扫描 + 一键连接**：手机端（原生插件）与 PC 端（netsh）都做
3. **修复常用链接页已知问题**（含"分类删空即消失"）
4. **手机端源码全量并入 hanasite/AUST 仓库**；开发期由 Claude 构建 debug APK，发布签名包由用户出

明确不做：PC 端 UI 重做、教务处/课表功能、iOS。

---

## 2. 视觉系统（已通过原型确认）

### 2.1 设计语言

- **A1 纯白极简扁平**：无阴影、无渐变、无发光；用 1px 发丝线做分隔与容器边界（行与行之间也有分隔线）
- 交互反馈只做：轻微变色、按压回弹（scale .97-.98）、图标按钮悬停染色

### 2.2 设计令牌

| 令牌 | 浅色 | 深色 |
|---|---|---|
| 背景 bg | #FFFFFF | #15202B |
| 正文 fg | #0F1419 | #F7F9F9 |
| 次要文字 sub | #536471 | #8B98A5 |
| 发丝线 line | #EFF3F4 | #38444D |
| 强调 blue | #1D9BF0（hover #1A8CD8） | 同左 |
| 浅蓝底 tint | #E8F5FE | rgba(29,155,240,.14) |
| 成功 ok / okbg | #068A5F / #E8F8F2 | #00BA7C / rgba(0,186,124,.16) |
| 错误 red / redtint | #F4212E / #FDECEE | 同左 |

实现方式：CSS 变量 + `.dark` 作用域覆盖（现架构已有深色模式，改为全令牌化，消除硬编码浅色）。

### 2.3 字体

- **内嵌 Inter 可变字体**（`www/fonts/inter-variable-latin.woff2`，latin 子集 48KB，SIL OFL 1.1 可商用可内嵌）
  - `@font-face` weight 范围 100-900；拉丁字母与数字用 Inter
  - 中文回退系统字体（Android 思源黑体 / iOS PingFang），不打包中文字体
- 排版规则：标题 800 / 名称 700 / 正文 400-500；标题 `letter-spacing:-.02em`；数字数据 `font-variant-numeric:tabular-nums`
- 不采用 Chirp（Twitter 私有字体，不可打包）

### 2.4 图标

- **Lucide 图标库**（ISC 协议），以内联 SVG sprite 方式嵌入 index.html（离线可用，不引 CDN）
- 初始集合（24 个）：wifi, signal, lock, check, zap, home, chart, star, refresh, globe, gradcap, book, library, mail, router, phone, laptop, code, bot, search, pencil, power, eye, alert
- 全部替换现有 emoji 图标；常用链接的"图标自选"改为 Lucide 图标选择器（固定集合 + 颜色跟随主题）

### 2.5 组件规范

- 列表行：icon 圆底 + 主文字 14/700 + 次文字 12/sub，行间发丝线
- 按钮：主按钮 #1D9BF0 胶囊；次按钮 1px 蓝描边胶囊；幽灵按钮 1px line 描边
- 徽章：成功=浅绿底绿字 ✅ 型；中性=灰底
- 底部弹卡（sheet）：圆角 24 顶部、拖拽条、无阴影，遮罩 rgba(15,20,25,.45)
- 步骤条：完成（绿底对勾）/ 进行中（蓝底转圈）/ 等待（空心圆）
- 提示条（snackbar）：#0F1419 深色胶囊，底部居中
- 空状态：灰圆图标 + 标题 + 说明 + 操作按钮

---

## 3. 信息架构（手机端）

底部三 Tab（替换顶部 Tab 栏）：

1. **首页**：网络状态卡（当前 SSID + 认证状态徽章）→「一键认证」→「校园 WiFi」卡（扫描列表）
2. **自助系统**：登录/验证码/用量三栏/账户信息/在线设备（现有功能迁移）
3. **常用链接**：分类链接格 + 编辑模式（现有功能迁移 + bug 修复）

保留：深色模式（跟随系统 + 手动切换）、配置持久化、DrCOM 认证流程、验证码弹窗。

---

## 4. WiFi 功能

### 4.1 手机端（Android）

**权限（AndroidManifest 新增）**

- `ACCESS_WIFI_STATE`、`CHANGE_WIFI_STATE`、`ACCESS_NETWORK_STATE`（普通权限）
- `NEARBY_WIFI_DEVICES`（API 33+，`usesPermissionFlags="neverForLocation"`）——运行时申请
- `ACCESS_FINE_LOCATION`（`maxSdkVersion="32"`，API ≤32 扫描所需）——运行时申请；API ≤32 还需系统定位服务开启，未开启时引导

**扫描**

- `WifiManager.startScan()` + `SCAN_RESULTS_AVAILABLE_ACTION` 广播接收结果
- 系统节流：前台 App 每 2 分钟最多 4 次；界面自动刷新间隔 30s，尊重节流（失败则保持旧数据 + 时间戳提示）
- 结果展示：SSID、信号强度（图标/格数）、加密状态（开放/需密码）、是否已保存（`getConfiguredNetworks` / suggestion 记录）、是否目标 SSID

**目标 SSID 配置**

- 可配置列表（默认：SSID 包含 `AUST` 视为目标；可在 App 内编辑）
- 保存的密码与配置存本机（Capacitor Preferences，键 `aust_wifi`）

**连接（Android 10+ 限制下的方案）**

- 机制：`WifiNetworkSuggestion`（API 29+，本 App minSdk 22，API<29 设备回退 `addNetwork` 路径或引导系统设置）
- 首次连接目标网络：
  1. 需密码 → 弹底部卡片输密码（可切明文；「保存此网络」默认勾选）
  2. 添加 suggestion → 系统弹窗/通知请用户允许一次（步骤条展示"等待系统确认"）
  3. 允许后系统自动完成连接；配置保存。**之后为真一键**：设备在范围内时系统自动重连（无需任何操作），App 内的"一键连接"按钮此时只做单点触发与连接状态核对
- 连接状态：`ConnectivityManager` + `WifiManager.getConnectionInfo()` 轮询/广播
- 状态机：待机 → 扫描中 → 发现目标 → [输密码] → 连接中（保存配置/等待系统确认/获取 IP 三步）→ 成功 | 失败（原因 + 重试，保留配置）
- **兜底**：权限被拒/ROM 限制（MIUI 等）/ 任何异常 → 「打开系统 WiFi 设置」入口（`Settings.Panel.ACTION_WIFI`，API 29+；低版本 `ACTION_WIFI_SETTINGS`）

**自研原生插件（Java，`cn.edu.aust.connectease.WifiPlugin`）**

- 方法：`scan()`、`connect({ssid, password, save})`、`getStatus()`、`openWifiSettings()`、`requestPermissions()`
- 事件：`scanResult`、`connectState`
- 注册：MainActivity `registerPlugin(WifiPlugin.class)`
- 不引入社区 WiFi 插件（维护参差、权限模型不匹配；自研约 300 行可控）

### 4.2 PC 端（Windows，tkinter 保持现有观感）

- 扫描：`netsh wlan show networks mode=bssid` 解析
- 连接：`netsh wlan connect name=<SSID>`；未保存的 SSID 先 `netsh wlan add profile`（生成 profile XML，WPA 需弹窗输一次密码并保存），再 connect
- 状态：`netsh wlan show interfaces` 轮询
- UI：新增"校园 WiFi"卡片（沿用现有 tkinter 风格），列表 + 一键连接；已保存 SSID 为真一键
- 版本号 v1.3

---

## 5. 常用链接页修复（含已确认根因）

| # | 问题 | 修复 |
|---|---|---|
| 1 | URL 无协议头（如 `github.com`）→ 导航到 `https://localhost/...`，白屏且 App 界面丢失 | 添加时自动补 `https://`并校验；全部打开动作走统一 `openLink()`（显式校验后再交给系统浏览器） |
| 2 | 名字含 `<`、`&` 等字符破坏渲染（innerHTML 拼接未转义） | 渲染改用 textContent / 转义 |
| 3 | 删除无确认无撤销 | 删除前确认；操作后 snackbar 提供「撤销」 |
| 4 | **分类删空即消失**（`filter(s=>s.items.length>0)` 且默认分类无恢复入口）——用户已确认命中 | 分类不再自动消失：清空后保留标题 + 空状态 + 「恢复默认链接」按钮；分类整体删除改为编辑模式下的显式操作（带确认） |
| 5 | 深色模式下 12 个图标底色为硬编码浅色 | 全部改为令牌变量 |
| 6 | 编辑模式"一碰就拖"，想滚动却拖动了图标 | 拖拽改由手柄（⠿）触发；其余区域可正常滚动 |
| 7 | 图标输入框 maxlength=4 截断组合 emoji | 改为 Lucide 图标选择器（问题自然消失） |
| 8 | 编辑入口两个按钮（编辑/添加）冗余 | 精简为右上角单个「编辑」按钮，编辑态内出现添加/拖拽 |

保留：默认三大分类（校园官方/学习科研/生活服务）+「⭐ 我的链接」，拖拽排序、增删、持久化。

---

## 6. 仓库与构建

### 6.1 仓库结构（hanasite/AUST）

```
AUST/
├── README.md                    # 更新：手机端 v2.0 说明、新截图
├── school_auth_v*.py            # PC 脚本（原地不动，+ v1.3 新版本）
├── 安理校园网认证助手.exe
├── phone/                       # ← 新增：原 F:\Android\aust-app 全量源码
│   ├── www/index.html           # 单文件 UI+逻辑
│   ├── www/fonts/inter-variable-latin.woff2
│   ├── android/                 # Capacitor Android 工程（含自定义 WifiPlugin）
│   ├── capacitor.config.json
│   ├── package.json
│   ├── 打包部署指南.md
│   └── .gitignore               # node_modules/、build/、.gradle/、local.properties、*.apk
├── docs/superpowers/specs/      # 本设计文档
└── AUST校园认证助手.apk          # 保留旧版；后续新 APK 走 Releases
```

- 根 `.gitignore` 同步补充构建产物规则
- 设计原型（已确认的 mockup HTML）复制到 `docs/design/` 存档

### 6.2 版本

- 手机端 v2.0（versionName 2.0，appName 不变）
- PC 端 v1.3

### 6.3 构建流程

- 开发期：Claude 本地构建 debug APK（Android SDK：D:\Android，platform-34/build-tools-34；Gradle 用 Android Studio 自带 JDK 17），`adb install` 或传 APK 给用户真机安装
- 发布：用户在 Android Studio 出签名 release APK，传 GitHub Releases 附件（沿用现有发布方式）
- 每次改 `www/index.html` 后 `npx cap sync android`；字体/图标均为本地资源，无网络依赖

---

## 7. 验证与测试

- **手机端（真机，必需）**：WiFi 扫描列表正确性；首次连接流程（含系统确认）；二次一键连接；密码错误/不在范围/权限拒绝三个失败路径；DrCOM 认证；自助系统登录+用量+设备下线；常用链接增删改/拖拽/恢复默认/深色模式
- 模拟器：WiFi 建议和扫描行为不完整，只做 UI 层冒烟
- **PC 端**：本机 Windows 实测 netsh 扫描/连接/状态；回归认证流程

---

## 8. 风险

| 风险 | 缓解 |
|---|---|
| 国产 ROM（MIUI/ColorOS 等）对 WifiNetworkSuggestion 的额外限制或延迟 | 全流程保留"系统确认"文案；兜底跳系统 WiFi 设置 |
| Android 10/11/12/13 行为差异（确认形式、节流） | 统一按"系统确认一次"路径设计，失败路径全覆盖 |
| WebView 渲染字体/图标性能 | 字形子集 48KB、SVG sprite 轻量、无模糊无阴影 |
| 真机只有用户一台（版本覆盖有限） | 失败路径与兜底入口保证可用性；日志面板保留便于排查 |

---

## 9. 已确认决策记录

- 风格：A1 扁平 + 无阴影 + 1px 线条；Twitter 清新感；Inter 内嵌
- WiFi：两端都做；目标 SSID 可配置（默认 AUST*）；首次可"先连接后保存为下次一键"
- 源码：全量入 hanasite/AUST 仓库
- 构建：Claude 出 debug，用户出 release
- PC 端：只加功能，UI 不动
