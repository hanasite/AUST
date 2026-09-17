# AUST 校园认证助手

安徽理工大学 教务处 校园网认证工具 —— **手机端 App + 电脑端程序**。

- 📱 **手机端**：Android App（源码在 `phone/`，Capacitor + 单文件 Web UI）
- 💻 **电脑端**：Windows 程序（`school_auth_v1.3.py`，tkinter）
- 📚 **文档**：设计与实施文档在 `docs/`，构建步骤见 `phone/打包部署指南.md`

Gitee 镜像：<https://gitee.com/yosakun/aust>

特别鸣谢 [TraceRecursion/AUST-ConnectEase](https://github.com/TraceRecursion/AUST-ConnectEase)（本项目参考其实现），以及陪我熬夜的好队友 / 同伙 / 朋友 / 同学～ 仓库维护工作主要是 UI 和打包发布。

---

## 📥 下载安装

**手机端（v2.0 公测版）**
- 到本仓库 **Releases** 下载 `AUST-ConnectEase-v2.0-beta.apk` 安装
- ⚠️ v2.0 更换了应用签名，安装过旧版（v1.2 及以前）的用户需**先卸载旧版**再装
- 首次使用：填学号 / 密码 / 运营商 → 一键认证；「校园 WiFi」卡片可扫描并一键连接校园网

**电脑端**
- 仓库根目录 `安理校园网认证助手.exe`（v1.2-Lite，双击即用）
- 新脚本 `school_auth_v1.3.py`：需要 Python 3，运行后界面里带 WiFi 扫描/一键连接卡片
- 历史版本：见 Gitee Releases

---

## ✨ 功能

**通用**：Dr.COM 校园网一键认证 · 记住账号密码（仅存本机、不上传）

**手机端 v2.0（公测版）**
- 全新扁平化界面（类 Twitter 风格），深色模式全量适配，内嵌 Inter 字体，全矢量图标
- **WiFi 扫描与一键连接**：查看周围真实网络，自动识别校园网（默认 AUST 关键字，可自定义）
  - 连接方式可选：**系统弹窗**（Android 11+ 一键确认）/ **引导式**（手动连一次后自动重连，所有机型通用）
  - 首次连接成功后，进出校园由系统自动重连，无需任何操作
- 自助系统：用量查询、在线设备管理（下线 / 自定义名称图标）
- 常用链接：自定义导航、拖拽排序、误删可撤销、分类可恢复默认
- App 内「使用说明」：认证方式、连接方式、权限与隐私解释

**电脑端 v1.3**
- v1.2-Lite 全部功能（认证 / 验证码 / 设备管理）
- WiFi 卡片：扫描周围网络、一键连接已保存过的网络

---

## 🗒 使用说明要点

- **认证方式**：宽带（POST）用于电脑拨号 / 路由器接入；WiFi（GET）用于手机连上校园 WiFi 后认证（手机默认 GET）
- **连接方式**：系统弹窗（更快）/ 引导式（通用）——点连接后系统弹窗没出现时，切换为引导式即可
- **权限**：扫描 WiFi 需要「附近的设备」与「位置」权限；部分国产 ROM（vivo / 小米等）还需打开系统定位开关
- **隐私**：学号密码与 WiFi 密码仅保存在本机（已关闭云备份），不上传任何服务器

---

## 📝 更新日志

- **v2.0 公测版（Beta）** · 2026-09：全新界面；WiFi 扫描与一键连接；常用链接修复；App 内使用说明；手机端默认认证方式改为 GET ｜ 详见 [发布说明](docs/release-notes-v2.0-beta.md)
- v1.2 Pocket · 2026-04：手机版上线，类原生安卓风格，自定义 URL 导航 ｜ [下载](https://gitee.com/yosakun/aust/releases/download/v1.2Pocket/AUST%E6%A0%A1%E5%9B%AD%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.apk)
- v1.2-Lite：校园网设备管理，验证码手动输入 ｜ [下载](https://gitee.com/yosakun/aust/releases/download/v1.2-Lite/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E7%BD%91%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B-Lite.exe)
- v1.1：开机自启动、自定义背景颜色 ｜ [下载](https://gitee.com/yosakun/aust/releases/download/v1.1/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E7%BD%91%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.exe)
- v1.0：首个版本 ｜ [下载](https://gitee.com/yosakun/aust/releases/download/v1.0/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E7%BD%91%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.exe)

---

## 🧱 源码与构建

| 目录 / 文件 | 内容 |
|---|---|
| `phone/` | 手机端源码（Capacitor 6 + `www/index.html` 单文件 + Android 工程 + 图标工具），构建见 `phone/打包部署指南.md` |
| `school_auth_v*.py` | 电脑端脚本（tkinter，单文件） |
| `docs/` | 设计文档、实施计划、发布说明、设计原型 |
| `phone/tools/` | 图标 sprite 生成脚本、纯函数测试（`node test-pure.mjs`）、CDP 冒烟配方 |

---

## ⚠️ 已知问题（公测版）

- WiFi 连接状态在「系统隐藏本机 SSID 且同时连着其他 WiFi」时可能误报为已连接；不影响认证流程，重新扫描后自动恢复
- 应用保存的 WiFi 密码目前仅支持 WPA2 个人网络（校内 AUST 网络即为 WPA2）
- Android 9 及以下、Android 10 的连接路径未实机验证（欢迎对应机型用户反馈）

---

## 💬 反馈

v2.0 公测版主要用于**收集使用意见**——欢迎在 [GitHub Issues](https://github.com/hanasite/AUST/issues) 或 Gitee Issues 反馈问题与建议。

## 🔭 前瞻

教务处登录、课表查询等功能
