# CDP 冒烟测试配方（headless Edge + Chrome DevTools Protocol）

本项目 `www/index.html` 是单文件应用，无自动化测试框架。P1/P2 各任务的浏览器验证统一走
「headless Edge + CDP」：真实浏览器渲染 + 真实鼠标事件 + 可断言 DOM，脚本一次性放 `%TEMP%`、不入库。
本文件记录可复跑的配方，供后续贡献者在改动 UI/交互后做回归。

## 0. 前置

- Windows + 已装 Edge（验证时版本 153.0.4234.32，`--headless=new`）
- Node 18+，**Node 22/24 起自带全局 `WebSocket`**，无需 npm 依赖（本项目即用 Node 24）
- 不要用 agent-browser：本机无 Chrome 环境时会挂起（Task 3 实测）

## 1. 启动 headless Edge

```bash
# 独立临时 profile，避免污染用户 Edge；记住 PID 供收尾
mkdir -p "$TEMP/aust-cdp"
"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --headless=new --disable-gpu --remote-debugging-port=9223 \
  --user-data-dir="$TEMP/aust-cdp" --no-first-run about:blank &
```

收尾时只杀自己启动的 PID（`taskkill /F /PID <pid>`）。**不要** `taskkill /IM msedge.exe`，
会连带关闭用户前台 Edge 窗口。

## 2. 连接与页面加载

```js
// cdp.mjs —— Node 直连 CDP（每个命令都是 {id, method, params} 的 JSON 帧）
const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const ws = new WebSocket(list[0].webSocketDebuggerUrl);
// 常用命令：Page.enable / Runtime.enable / Log.enable（收 console.error 与异常）
```

页面地址用 `file://` 直开，**仓库路径含中文，必须 percent-encode**（交给 `encodeURI` 即可）：

```
file:///<encodeURI(仓库绝对路径)>/phone/www/index.html
```

视口统一模拟手机：`Emulation.setDeviceMetricsOverride {width:390, height:844,
deviceScaleFactor:2, mobile:true}`。每次场景起点：`Runtime.evaluate("localStorage.clear()")`
后 `Page.reload`，避免上一个场景的持久化状态串场。

## 3. 注入原生 WiFi 插件桩（关键）

页面在**脚本解析时**就按 `window.Capacitor?.Plugins?.Wifi` 是否存在决定
`Wifi.provider`（`NativeProvider` vs `MockProvider`），所以桩必须早于页面脚本：

```js
await send('Page.addScriptToEvaluateOnNewDocument', { source: `
  window.Capacitor = window.Capacitor || {};
  window.Capacitor.Plugins = window.Capacitor.Plugins || {};
  const calls = window.__wifiCalls = [];
  window.Capacitor.Plugins.Wifi = {
    checkPermissions: async () => { calls.push('checkPermissions'); return { granted: true, locationServiceOn: true }; },
    requestPermissions: async () => { calls.push('requestPermissions'); return { granted: true }; },
    openSettings: async () => { calls.push('openSettings'); return {}; },
    openLocationSettings: async () => { calls.push('openLocationSettings'); return {}; },
    scan: async (o) => { calls.push(['scan', o]); return { networks: [{ ssid: 'AUST-Student', level: 4, secured: true }], ts: Date.now() }; },
    connect: async (o) => { calls.push(['connect', o]); return { ok: true }; },
    getStatus: async () => { calls.push('getStatus'); return { connected: true, ssid: 'AUST-Student' }; }
  };` });
```

要点：命令名/返回值需匹配原生契约（`checkPermissions` 返回 `{granted, locationServiceOn}`
布尔；`scan` 返回 `{networks:[{ssid,level,secured}], ts}`）；每个方法 push 一条调用记录，
断言用 `window.__wifiCalls` 核对「UI 动作 → 原生调用」的映射。桩在下次 reload 前保持不变，
改桩行为要重新注入 + reload。

交互一律用真实鼠标事件（`Input.dispatchMouseEvent` mousePressed/mouseReleased），坐标经
`Runtime.evaluate` 取 `getBoundingClientRect()` 中心，不用 `element.click()` —— 这样才覆盖
真实命中区域/遮挡问题。

## 4. 关键场景清单

| 场景 | 步骤 | 断言 |
|---|---|---|
| 三 Tab 导览 | 依次点 首页 / 自助系统 / 常用链接 | `.tab-panel.active` 与 tabbar `.on` 同步；无 console error |
| 深色切换 | 点顶栏按钮 → 再点一次 | `documentElement.classList` 含/不含 `dark`；`meta[theme-color]` 随动；`localStorage.aust_darkmode` 落值 |
| 连接流程（桩） | 首页「一键连接」→ 等 flow 结束 | `__wifiCalls` 顺序含 scan→connect→getStatus；成功 snackbar；失败分支把 `connect` 桩改成 `{ok:false,error:'密码错误'}` |
| 目标编辑器 | 打开 targets sheet → 增删关键字 → 关闭重开 | 列表与 `localStorage` 持久化一致；空列表提示态；重扫计数递增（scan 桩计数） |
| 首屏/回归 | 清 localStorage + reload | 默认导航分类齐全；截图 `Page.captureScreenshot` 供人工比对 |

## 5. 收尾与局限

- 结束：关闭 WebSocket → `taskkill /F /PID <自己启动的 msedge pid>` → 删临时 profile
- 保存证据：截图 PNG + `Runtime.evaluate` 断言输出；console 异常经 `Runtime.exceptionThrown`
  与 `Log.entryAdded` 采集，期望 0 条
- **headless ≠ 真机**：权限弹窗、系统 WiFi sheet、ROM 差异（vivo/MIUI 定位开关）无法覆盖，
  发版前仍需真机验收（见 `docs/superpowers/plans/release-checklist-v2.0.md`）
- 纯函数（normalizeUrl/escHtml/ensureSections）不必起浏览器，直接跑 `node phone/tools/test-pure.mjs`
