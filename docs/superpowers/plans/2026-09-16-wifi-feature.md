# AUST WiFi 一键连接实施计划（Plan 2/3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 WiFi 扫描 + 一键连接的完整功能：手机端自研 Capacitor 原生插件（Java）+ 前端接入 Plan 1 已完成的流程 UI；PC 端 v1.3 用 netsh 实现同功能（UI 保持 tkinter 现状，只加卡片）。

**Architecture:** 手机端：`WifiPlugin`（Java，`cn.edu.aust.connectease`）通过 `WifiNetworkSuggestion`（API 29+）实现"首次系统确认一次、之后自动重连"，API<29 回退 `addNetwork`；插件无事件推送，全部为 Promise 方法，前端 `WifiFlow` 状态机在 Plan 1 Task 7 已就位，本计划只替换 provider 并补错误处理。PC 端：`school_auth_v1.3.py` 在 v1.2lite 基础上新增 netsh 封装与 WiFi 卡片。

**Tech Stack:** Java 17 语法（compileSdk 34 / minSdk 22）、Capacitor 6 Plugin API、Python 3 + tkinter + subprocess(netsh)。

## Global Constraints

- 设计文档：`docs/superpowers/specs/2026-09-16-aust-v2-design.md` §4 为功能权威
- 工作目录：`F:\kakuns开源项目\AUST`（分支 `feat/v2.0`）；手机端在 `phone/`，PC 端在仓库根
- **WifiProvider 签名（Plan 1 Task 7 冻结，不得改动）**：
  - `scan({targets:string[]}) -> Promise<{networks:[{ssid:string, level:0-4, secured:boolean}], ts:number}>`
  - `connect({ssid:string, password?:string, secured:boolean, save:boolean}) -> Promise<{ok:boolean, status?:string, error?:string}>`
  - `getStatus() -> Promise<{connected:boolean, ssid:string|null}>`
- 构建命令同 Plan 1：`cd phone/android && JAVA_HOME="D:/AndroidStudio/jbr" ./gradlew assembleDebug`
- **Android 10+ 现实约束（写进所有文案与代码注释，不得承诺静默连接）**：第三方 App 只能投递"网络建议"，首次需用户在系统弹窗/通知中允许一次；之后由系统自动重连
- 所有用户可见文案沿用 v2 扁平语言（中英标点统一，无 emoji）
- 提交信息 `feat(phone,wifi): …` / `feat(pc): …`

---

### Task 1: WifiPlugin 原生插件（扫描 + 权限 + 状态）

**Files:**
- Create: `phone/android/app/src/main/java/cn/edu/aust/connectease/WifiPlugin.java`
- Modify: `phone/android/app/src/main/AndroidManifest.xml`
- Modify: `phone/android/app/src/main/java/cn/edu/aust/connectease/MainActivity.java`

**Interfaces:**
- Produces（本任务）：`WifiPlugin.scan()` / `checkPermissions()` / `getStatus()` / `openSettings()` 的 JS 侧名称为 `scan` `checkPermissions` `getStatus` `openSettings`（Capacitor 自动映射 `@PluginMethod` 方法名）
- Produces（Task 2 继续在同一文件加 `connect`）

- [ ] **Step 1: Manifest 权限**

`AndroidManifest.xml`：根标签加 `xmlns:tools="http://schemas.android.com/tools"`；在现有权限段追加：

```xml
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
<uses-permission android:name="android.permission.CHANGE_WIFI_STATE" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="32" />
<uses-permission android:name="android.permission.NEARBY_WIFI_DEVICES"
    android:usesPermissionFlags="neverForLocation" tools:targetApi="tiramisu" />
```

- [ ] **Step 2: MainActivity 注册插件**

```java
package cn.edu.aust.connectease;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(WifiPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
```

- [ ] **Step 3: 写 WifiPlugin（扫描与权限部分）**

`WifiPlugin.java`（本步骤先落全文；其中 `connect` 方法体在 Task 2 的 Step 中给出——**本步骤先写 `connect` 的占位实现 `call.reject("not implemented", "NOT_IMPL")`**，保证本任务可独立编译验证）：

```java
package cn.edu.aust.connectease;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.location.LocationManager;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.wifi.ScanResult;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@CapacitorPlugin(name = "Wifi")
public class WifiPlugin extends Plugin {

    private static final int REQ_PERM = 7301;

    private WifiManager wifi() {
        return (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
    }

    private String requiredPermission() {
        return Build.VERSION.SDK_INT >= 33
                ? Manifest.permission.NEARBY_WIFI_DEVICES
                : Manifest.permission.ACCESS_FINE_LOCATION;
    }

    private boolean hasPerm() {
        return ContextCompat.checkSelfPermission(getContext(), requiredPermission())
                == PackageManager.PERMISSION_GRANTED;
    }

    /** API<33 时扫描需要系统定位开关打开 */
    private boolean locationServiceOn() {
        if (Build.VERSION.SDK_INT >= 33) return true;
        LocationManager lm = (LocationManager) getContext().getSystemService(Context.LOCATION_SERVICE);
        try {
            return lm != null && lm.isLocationEnabled();
        } catch (Exception e) {
            return false;
        }
    }

    @PluginMethod
    public void checkPermissions(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("granted", hasPerm());
        ret.put("locationServiceOn", locationServiceOn());
        call.resolve(ret);
    }

    @PluginMethod
    public void requestPermissions(PluginCall call) {
        if (hasPerm()) {
            JSObject ret = new JSObject();
            ret.put("granted", true);
            call.resolve(ret);
            return;
        }
        bridge.saveCall(call); // 保存到 default 槽位，权限回调后取出
        getActivity().requestPermissions(new String[] { requiredPermission() }, REQ_PERM);
    }

    @Override
    public void handleRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.handleRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQ_PERM) return;
        PluginCall saved = bridge.getSavedCall(); // 无参版取 default 槽；若该版本签名不同，查 Bridge.java 用 getSavedCall("default")
        boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (saved != null) {
            JSObject ret = new JSObject();
            ret.put("granted", granted);
            saved.resolve(ret);
        }
    }

    @PluginMethod
    public void scan(PluginCall call) {
        if (!hasPerm()) {
            call.reject("需要 WiFi 权限", "PERM_DENIED");
            return;
        }
        if (!locationServiceOn()) {
            call.reject("需要打开系统定位开关", "LOCATION_OFF");
            return;
        }
        final WifiManager wm = wifi();
        if (wm == null) {
            call.reject("WiFi 服务不可用", "NO_SERVICE");
            return;
        }
        // 先注册广播，再触发扫描；12 秒超时后回退到缓存的扫描结果
        final PluginCall pending = call;
        final Context ctx = getContext().getApplicationContext();
        final java.util.concurrent.atomic.AtomicBoolean done = new java.util.concurrent.atomic.AtomicBoolean(false);
        final BroadcastReceiver[] holder = new BroadcastReceiver[1];
        holder[0] = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (done.compareAndSet(false, true)) {
                    try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                    resolveScan(pending, wm);
                }
            }
        };
        ContextCompat.registerReceiver(ctx, holder[0],
                new IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        boolean started = wm.startScan();
        if (!started) {
            // 系统节流中：立即用缓存结果返回
            if (done.compareAndSet(false, true)) {
                try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                resolveScan(pending, wm);
            }
            return;
        }
        getBridge().getActivity().getWindow().getDecorView().postDelayed(() -> {
            if (done.compareAndSet(false, true)) {
                try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                resolveScan(pending, wm);
            }
        }, 12000);
    }

    private void resolveScan(PluginCall call, WifiManager wm) {
        List<ScanResult> results;
        try {
            results = wm.getScanResults();
        } catch (SecurityException e) {
            call.reject("需要 WiFi 权限", "PERM_DENIED");
            return;
        }
        Map<String, ScanResult> best = new LinkedHashMap<>();
        for (ScanResult r : results) {
            if (r.SSID == null || r.SSID.isEmpty()) continue; // 隐藏网络
            ScanResult cur = best.get(r.SSID);
            if (cur == null || r.level > cur.level) best.put(r.SSID, r);
        }
        JSArray arr = new JSArray();
        for (ScanResult r : best.values()) {
            JSObject n = new JSObject();
            n.put("ssid", r.SSID);
            n.put("level", WifiManager.calculateSignalLevel(r.level, 5)); // 0-4
            String cap = r.capabilities == null ? "" : r.capabilities;
            n.put("secured", cap.contains("WPA") || cap.contains("WEP") || cap.contains("SAE") || cap.contains("PSK"));
            arr.put(n);
        }
        JSObject ret = new JSObject();
        ret.put("networks", arr);
        ret.put("ts", System.currentTimeMillis());
        call.resolve(ret);
    }

    @PluginMethod
    public void getStatus(PluginCall call) {
        JSObject ret = new JSObject();
        boolean connected = false;
        try {
            ConnectivityManager cm = (ConnectivityManager) getContext().getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm != null && cm.getActiveNetwork() != null) {
                NetworkCapabilities caps = cm.getNetworkCapabilities(cm.getActiveNetwork());
                connected = caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
            }
        } catch (Exception ignored) {}
        String ssid = null;
        WifiManager wm = wifi();
        if (wm != null) {
            try {
                android.net.wifi.WifiInfo info = wm.getConnectionInfo();
                if (info != null && info.getSSID() != null) {
                    String s = info.getSSID().replace("\"", "");
                    if (!s.startsWith("<")) ssid = s; // "<unknown ssid>" 等占位
                }
            } catch (Exception ignored) {}
        }
        ret.put("connected", connected);
        ret.put("ssid", ssid);
        call.resolve(ret);
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        try {
            Intent intent;
            if (Build.VERSION.SDK_INT >= 29) {
                intent = new Intent(Settings.Panel.ACTION_WIFI);
            } else {
                intent = new Intent(Settings.ACTION_WIFI_SETTINGS);
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        } catch (Exception e) {
            // 面板不可用时回退设置页
            Intent intent = new Intent(Settings.ACTION_WIFI_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void connect(PluginCall call) {
        call.reject("not implemented", "NOT_IMPL"); // Task 2 实现
    }
}
```

**实现提示**: `bridge.getSavedCall()` 无参版在部分 Capacitor 版本需改为 `getSavedCall("default")`——编译报错时对照 `phone/node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/Bridge.java` 的实际签名调整（Task 1 Step 4 编译时会暴露）。

- [ ] **Step 4: 编译验证**

```bash
cd "F:/kakuns开源项目/AUST/phone" && npx cap sync android && cd android && JAVA_HOME="D:/AndroidStudio/jbr" ./gradlew assembleDebug
```

Expected: `BUILD SUCCESSFUL`。

- [ ] **Step 5: 真机验证扫描（用户执行）**

安装 `phone/android/app/build/outputs/apk/debug/app-debug.apk`。打开 App → 首页 WiFi 卡：
1. 首次弹系统权限框 → 允许 → 列表显示真实扫描结果（含宿舍/教学楼 SSID），带信号强度
2. 拒绝权限后重开 → 卡片显示"需要 WiFi 权限"提示与重试（Plan 1 Task 7 的状态已覆盖；本任务验证提示文案正确）
3. Android 13+ 机型：确认系统设置里本 App 权限显示为"附近的设备"

- [ ] **Step 6: Commit**

```bash
git add phone/android
git commit -m "feat(phone,wifi): native plugin — scan, permissions, status, settings"
```

---

### Task 2: WifiPlugin connect（网络建议 + 旧版本回退）

**Files:**
- Modify: `phone/android/app/src/main/java/cn/edu/aust/connectease/WifiPlugin.java`（替换 `connect` 占位）

**Interfaces:**
- Produces: `connect({ssid, password?, secured, save})` → `{ok:boolean, status:string, error?:string}`（status: `"ADDED"` / `"DUPLICATE"` / `"UNSUPPORTED"`）

- [ ] **Step 1: 实现 connect**

替换 `connect` 方法体（并在文件 import 增加 `android.net.wifi.WifiConfiguration`、`android.net.wifi.WifiNetworkSuggestion`、`java.util.Collections`）：

```java
    @PluginMethod
    public void connect(PluginCall call) {
        if (!hasPerm()) {
            call.reject("需要 WiFi 权限", "PERM_DENIED");
            return;
        }
        final WifiManager wm = wifi();
        if (wm == null) {
            call.reject("WiFi 服务不可用", "NO_SERVICE");
            return;
        }
        String ssid = call.getString("ssid");
        String password = call.getString("password", "");
        boolean secured = Boolean.TRUE.equals(call.getBoolean("secured", true));
        if (ssid == null || ssid.isEmpty()) {
            call.reject("缺少 SSID", "BAD_ARGS");
            return;
        }
        JSObject ret = new JSObject();
        if (Build.VERSION.SDK_INT >= 29) {
            WifiNetworkSuggestion.Builder b = new WifiNetworkSuggestion.Builder().setSsid(ssid);
            if (secured && password != null && !password.isEmpty()) {
                b.setWpa2Passphrase(password);
            }
            int status = wm.addNetworkSuggestions(Collections.singletonList(b.build()));
            if (status == WifiManager.STATUS_NETWORK_SUGGESTIONS_SUCCESS) {
                ret.put("ok", true);
                ret.put("status", "ADDED");
            } else if (status == 2 /* STATUS_NETWORK_SUGGESTIONS_ERROR_ADD_DUPLICATE */) {
                ret.put("ok", true);
                ret.put("status", "DUPLICATE");
            } else {
                ret.put("ok", false);
                ret.put("status", "ERROR_" + status);
                ret.put("error", "系统拒绝添加网络建议（code " + status + "）");
            }
            call.resolve(ret);
            return;
        }
        // API < 29 回退：直接配置并连接（该版本允许第三方 App 操作）
        try {
            WifiConfiguration conf = new WifiConfiguration();
            conf.SSID = "\"" + ssid + "\"";
            if (secured && password != null && !password.isEmpty()) {
                conf.preSharedKey = "\"" + password + "\"";
            } else {
                conf.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.NONE);
            }
            int netId = wm.addNetwork(conf);
            if (netId == -1) {
                ret.put("ok", false);
                ret.put("status", "ADD_FAILED");
                ret.put("error", "保存网络配置失败（密码可能不正确）");
            } else {
                wm.disconnect();
                wm.enableNetwork(netId, true);
                wm.reconnect();
                ret.put("ok", true);
                ret.put("status", "ADDED");
            }
        } catch (SecurityException e) {
            call.reject("需要更改 WiFi 状态的权限", "PERM_DENIED");
            return;
        }
        call.resolve(ret);
    }
```

- [ ] **Step 2: 编译**

```bash
cd "F:/kakuns开源项目/AUST/phone" && npx cap sync android && cd android && JAVA_HOME="D:/AndroidStudio/jbr" ./gradlew assembleDebug
```

Expected: `BUILD SUCCESSFUL`。

- [ ] **Step 3: JS 侧接入原生 provider（替换 mock）**

`phone/www/index.html` 中（Plan 1 Task 7 的 Wifi 模块处）：

```js
const NativeProvider = {
  _p(){ return window.Capacitor?.Plugins?.Wifi; },
  async checkPermissions(){ return this._p().checkPermissions(); },
  async requestPermissions(){ return this._p().requestPermissions(); },
  async scan(opts){ return this._p().scan(opts||{}); },
  async connect(o){ return this._p().connect(o); },
  async getStatus(){ return this._p().getStatus(); },
  async openSettings(){ return this._p().openSettings(); }
};
const Wifi = {
  provider: (typeof window!=='undefined' && window.Capacitor?.Plugins?.Wifi) ? NativeProvider : MockProvider,
  setProvider(p){ this.provider=p; },
  scan(o){ return this.provider.scan(o); },
  connect(o){ return this.provider.connect(o); },
  getStatus(){ return this.provider.getStatus(); }
};
```

`WifiFlow.refresh()` 的错误分支补齐（依赖错误 code 字符串，Plan 1 已有状态渲染点）：

```js
catch(e){
  const code = e?.code || e?.message || '';
  if (String(code).includes('PERM_DENIED')) {
    this.renderNotice('需要 WiFi 权限才能扫描','去授权', ()=>Wifi.provider.requestPermissions().then(()=>this.refresh()));
  } else if (String(code).includes('LOCATION_OFF')) {
    this.renderNotice('请打开系统定位开关（Android 12 及以下扫描 WiFi 所需）','去设置', ()=>Wifi.provider.openSettings());
  } else {
    this.renderNotice('扫描失败，稍后自动重试','重试', ()=>this.refresh());
  }
}
```

连接超时（`waitConnected` 20s 未连上）的失败 sheet 增加次要按钮「打开系统 WiFi 设置」（调用 `Wifi.provider.openSettings()`）——对应设计文档 §4.1 兜底。

- [ ] **Step 4: 真机全流程验证（用户执行）**

在宿舍/教学楼信号范围内：
1. 点目标网络（首次，需密码）→ 输密码 → 保存并连接 → 系统通知/弹窗出现"允许连接到 AUST-xx"→ 允许 → 步骤条走到"已连接" → snackbar「已连接并保存，下次一键即连」
2. 关闭手机 WiFi → 再打开 → 观察**系统自动重连**（无需打开 App）——即"真一键"
3. 离开信号范围点连接 → 20s 超时 → 失败 sheet → 「打开系统 WiFi 设置」按钮能拉起系统面板
4. 回归：DrCOM 认证、自助系统功能不受影响

- [ ] **Step 5: Commit**

```bash
git add phone
git commit -m "feat(phone,wifi): connect via network suggestion + native provider integration"
```

---

### Task 3: PC 端 v1.3 — netsh 扫描/连接 + tkinter 卡片

**Files:**
- Create: `school_auth_v1.3.py`（基于 `school_auth_v1.2lite.py` 完整复制后增量修改）
- Test: 手动运行 + 内置 CLI 自测模式

**Interfaces:**
- Produces: `wifi_scan() -> list[dict{ssid, signal:int, secured:bool}]`；`wifi_status() -> {connected:bool, ssid:str|None}`；`wifi_connect(ssid, password=None, secured=False) -> (bool, str)`
- Consumes: 无（独立脚本）

- [ ] **Step 1: 复制基线并加 WiFi 模块（文件顶部，import 区之后）**

```python
import subprocess, re, tempfile
from xml.sax.saxutils import escape as _xml_escape

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def _netsh(args):
    """执行 netsh 并解码输出（中文 Windows 为 GBK 代码页）"""
    try:
        r = subprocess.run(["netsh", *args], capture_output=True,
                           creationflags=_CREATE_NO_WINDOW, timeout=15)
        out = r.stdout.decode("gbk", errors="replace") + r.stderr.decode("gbk", errors="replace")
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "timeout"

def wifi_scan():
    """返回 [{'ssid','signal','secured'}...]，按信号降序。依赖 netsh 输出结构而非文案语言。"""
    code, out = _netsh(["wlan", "show", "networks", "mode=bssid"])
    if code != 0:
        return []
    nets = []
    for block in re.split(r"\r?\n(?=SSID \d+\s*:)", out):
        m = re.match(r"SSID \d+\s*:\s*(.*)", block)
        if not m:
            continue
        ssid = m.group(1).strip()
        if not ssid:
            continue  # 隐藏网络
        sig = re.search(r":\s*(\d+)%", block)
        secured = not re.search(r"开放|Open", block, re.IGNORECASE)
        nets.append({"ssid": ssid, "signal": int(sig.group(1)) if sig else 0, "secured": secured})
    # 同名去重取最强
    best = {}
    for n in nets:
        if n["ssid"] not in best or n["signal"] > best[n["ssid"]]["signal"]:
            best[n["ssid"]] = n
    return sorted(best.values(), key=lambda x: -x["signal"])

def wifi_status():
    code, out = _netsh(["wlan", "show", "interfaces"])
    if code != 0:
        return {"connected": False, "ssid": None}
    m = re.search(r"SSID\s*:\s*(.+)", out)
    state_ok = bool(re.search(r"已连接|Connected", out, re.IGNORECASE))
    ssid = m.group(1).strip() if m else None
    return {"connected": state_ok, "ssid": ssid}

_PROFILE_XML = """<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid}</name>
  <SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>auto</connectionMode>
  <MSM><security><authEncryption>
    <authentication>{auth}</authentication><encryption>{enc}</encryption>
    <useOneX>false</useOneX>
  </authEncryption>{shared_key}</security></MSM>
</WLANProfile>
"""

def wifi_connect(ssid, password=None, secured=False):
    """返回 (成功?, 信息)。已保存过的 SSID 直接 connect（真一键）。"""
    code, out = _netsh(["wlan", "show", "profiles", "name=" + ssid])
    profiled = code == 0 and ("所有用户配置文件" in out or "All User Profile" in out)
    if not profiled:
        if secured and not password:
            return False, "该网络需要密码"
        key = (f"<sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
               f"<keyMaterial>{_xml_escape(password or '')}</keyMaterial></sharedKey>"
               if secured else "")
        xml = _PROFILE_XML.format(ssid=_xml_escape(ssid),
                                  auth="WPA2PSK" if secured else "open",
                                  enc="AES" if secured else "none", shared_key=key)
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                         encoding="utf-8") as f:
            f.write(xml)
            path = f.name
        code, out = _netsh(["wlan", "add", "profile", "filename=" + path, "user=current"])
        if code != 0:
            return False, "保存网络配置失败"
    code, out = _netsh(["wlan", "connect", "name=" + ssid])
    if code != 0:
        return False, "连接命令失败"
    time.sleep(3)
    st = wifi_status()
    return (st["connected"] and st["ssid"] == ssid), ("已连接 " + ssid if st["ssid"] == ssid else "已发起连接，请稍候")
```

**注意**: `_netsh(["wlan","show","profiles","name="+ssid])` 的 profile 判定按输出含"所有用户配置文件"/"All User Profile"；若命中失败也只会走"重建 profile"路径（幂等，无副作用）。

- [ ] **Step 2: 快速自测（不需要 GUI）**

在文件末尾 `if __name__ == "__main__":` 前加：

```python
def _selftest():
    nets = wifi_scan()
    print(f"[scan] {len(nets)} 个网络")
    for n in nets[:8]:
        print(f"  {n['ssid']:<24} {n['signal']:>3}%  {'加密' if n['secured'] else '开放'}")
    print("[status]", wifi_status())

if __name__ == "__main__" and "--wifi-selftest" in sys.argv:
    _selftest()
    sys.exit(0)
```

运行（本机 Windows 实机）：

```bash
cd "F:/kakuns开源项目/AUST" && python school_auth_v1.3.py --wifi-selftest
```

Expected: 列出附近真实 WiFi（含中文 SSID 不乱码）；`[status]` 显示当前连接。**若中文乱码**：说明代码页非 GBK，将 `decode("gbk")` 改为 `decode("utf-8", errors="replace")` 重试并在 commit 注明。

- [ ] **Step 3: GUI 卡片（沿用现有 tkinter 风格）**

在认证卡与选项卡之间插入"校园 WiFi"卡片（沿用现有 `card` 样式与 `threading` + `self.after` 模式）：

- 顶部：`扫描` 按钮 + 状态行（上次扫描时间 / 当前连接 SSID）
- 列表：ScrolledText 或若干 Label 行（现有 v1.2lite 无滚动容器时，用 `tk.Frame` + 最多 8 行 Label + 按钮，保持简单）
- 目标网络（SSID 含 `AUST`，大小写不敏感）行高亮 + 显示「一键连接」按钮；非目标行显示「连接」
- 需密码且未保存过 → 弹出现有风格的小输入框（`tkinter.simpledialog.askstring`，`show="*"`）取得密码后连接
- 所有 netsh 调用放到后台线程，结果经 `self.after(0, ...)` 回主线程（沿用文件中现有线程模式；这是 tkinter 的硬性要求，不得在主线程调 netsh）

- [ ] **Step 4: 手动验证**

运行 `python school_auth_v1.3.py` → 点扫描 → 列表出现；在你的路由器 WiFi（已连接过的）上点「一键连接」→ 5 秒内状态行显示已连接（**验证前先确认该网络已保存过**；测试新 SSID 需用户确认密码后手动验证）。回归：一键认证、验证码、设备管理不受影响。

- [ ] **Step 5: Commit**

```bash
git add school_auth_v1.3.py
git commit -m "feat(pc): v1.3 — wifi scan + one-click connect via netsh"
```

---

## Self-Review 记录

- 覆盖检查：spec §4.1 权限/扫描/连接/自研插件/兜底（Task 1-2）、§4.2 PC 端（Task 3）全部落任务
- 已知风险留在任务内：`bridge.getSavedCall` 签名差异（Task 1 Step 3 有查源码指引）；netsh 中文代码页（Task 3 Step 2 有回退指引）
- WifiProvider 三方法签名与 Plan 1 Task 7 冻结版一致（本计划未新增第四方法，`checkPermissions/requestPermissions/openSettings` 为可选扩展，通过 `Wifi.provider` 透传访问）
