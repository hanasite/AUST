# AUST

#### 介绍
安徽理工大学 教务处 校园网 课表 等相关的仓库

#### 软件架构
软件架构说明

特别鸣谢：
https://github.com/TraceRecursion/AUST-ConnectEase   我们参考此文件实现

陪我我熬夜的好队友/同伙/朋友/同学

我仅做了ui和打包发布工作。


gitee仓库链接
https://gitee.com/yosakun/aust


#### 安装教程(可访问gitee快速下载)

校园网认证：点击链接下载exe，双击打开就行了

v1.0   链接
https://gitee.com/yosakun/aust/releases/download/v1.0/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E7%BD%91%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.exe


v1.1  链接
https://gitee.com/yosakun/aust/releases/download/v1.1/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.exe


v1.2-Lite  链接
https://gitee.com/yosakun/aust/releases/download/v1.2-Lite/%E5%AE%89%E7%90%86%E6%A0%A1%E5%9B%AD%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B-Lite.exe


2026/4/6手机版正式上线
v1.2—Pocket  链接
https://gitee.com/yosakun/aust/releases/download/v1.2Pocket/AUST%E6%A0%A1%E5%9B%AD%E8%AE%A4%E8%AF%81%E5%8A%A9%E6%89%8B.apk



#### 更新使用说明

校园网认证：

v1.0   
双击打开，填入学号/密码/运营商/连接类型

v1.1
增加开机自启动，增加自定义背景颜色，优化UI布局

v1.2-lite
添加校园网设备管理，优化UI布局，验证码需手动输入

v1.2Pocket
UI美化，类原生安卓风格，添加了自定义URL导航，优化交互逻辑！

v2.0 — Pocket 全新改版
- 全新扁平化界面（类 Twitter 风格），深色模式全量适配，内嵌 Inter 字体
- 新增 WiFi 扫描与一键连接：首次连接经系统弹窗一键确认（Android 11+），之后系统自动重连
- 修复常用链接：链接格式校验、删除确认/撤销、分类清空不再消失（可恢复默认）
- 手机端源码已开源于本仓库 `phone/` 目录（Capacitor + Android 工程）

说明：学号/WiFi 密码仅保存在本机（已关闭云备份）；WiFi 连接对 Android 11+ 通过系统「添加网络」弹窗完成，Android 10 及以下走系统建议机制。

存在的问题：
- 自助系统加载问题已在 v2.0 修复。
- WiFi 连接状态在「系统隐藏本机 SSID（Android 12+ 隐私设置）且手机同时连着其他 WiFi」时可能误报为已连接；不影响认证流程，重新扫描后自动恢复。
- 通过应用保存的 WiFi 密码目前仅支持 WPA2 个人网络（校内 AUST 网络即为 WPA2）。

#### 手机端源码构建

源码位于 `phone/`，构建步骤见 `phone/打包部署指南.md`（Node 18+ / Android Studio / JDK 17）。

前瞻
教务处登录，课表查询等功能
