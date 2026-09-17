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
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiManager;
import android.net.wifi.WifiNetworkSuggestion;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@CapacitorPlugin(
    name = "Wifi",
    permissions = {
        @Permission(strings = { Manifest.permission.NEARBY_WIFI_DEVICES }, alias = "nearbyWifi"),
        @Permission(strings = { Manifest.permission.ACCESS_FINE_LOCATION }, alias = "fineLocation")
    }
)
public class WifiPlugin extends Plugin {

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

    private boolean hasLocationPerm() {
        return ContextCompat.checkSelfPermission(getContext(), Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * API 33+ 时向系统申请的一组权限别名：部分 CN ROM（vivo/MIUI 等）即使只扫 WiFi
     * 也要求定位权限才会给出扫描结果，所以两个一起申请（系统会合并成一个弹窗）
     */
    private String[] requiredPermissionAliases() {
        return Build.VERSION.SDK_INT >= 33
                ? new String[] { "nearbyWifi", "fineLocation" }
                : new String[] { "fineLocation" };
    }

    /** 主权限 +（33+ 时的）定位权限都拿到了才算齐 */
    private boolean hasRequiredPerms() {
        if (!hasPerm()) return false;
        return Build.VERSION.SDK_INT < 33 || hasLocationPerm();
    }

    /** 所有 SDK 版本都检查真实定位开关：CN ROM 在 33+ 上不开定位同样不给扫描结果 */
    private boolean locationServiceOn() {
        LocationManager lm = (LocationManager) getContext().getSystemService(Context.LOCATION_SERVICE);
        try {
            if (lm == null) return false;
            if (Build.VERSION.SDK_INT >= 28) return lm.isLocationEnabled();
            return lm.isProviderEnabled(LocationManager.GPS_PROVIDER)
                    || lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
        } catch (Exception e) {
            return false;
        }
    }

    @PluginMethod
    public void checkPermissions(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("granted", hasPerm());
        ret.put("locationServiceOn", locationServiceOn());
        ret.put("locationPermission", hasLocationPerm());
        call.resolve(ret);
    }

    @PluginMethod
    public void requestPermissions(PluginCall call) {
        if (hasRequiredPerms()) {
            resolvePermissionState(call);
            return;
        }
        // Capacitor 6：走注解式权限流（@PermissionCallback），调用由 Bridge 保存/回传
        requestPermissionForAliases(requiredPermissionAliases(), call, "permissionsCallback");
    }

    @PermissionCallback
    private void permissionsCallback(PluginCall call) {
        resolvePermissionState(call);
    }

    /** 权限弹窗（或已授权短路）后只结算一次：granted = 主权限结果 */
    private void resolvePermissionState(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("granted", hasPerm());
        ret.put("locationPermission", hasLocationPerm());
        call.resolve(ret);
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
        // 先注册广播，再触发扫描；广播 / 缓存回退 / 20s 超时三条路径共用 done 标志，保证只结算一次
        final PluginCall pending = call;
        final Context ctx = getContext().getApplicationContext();
        final java.util.concurrent.atomic.AtomicBoolean done = new java.util.concurrent.atomic.AtomicBoolean(false);
        final BroadcastReceiver[] holder = new BroadcastReceiver[1];
        holder[0] = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (done.compareAndSet(false, true)) {
                    try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                    resolveScan(pending, wm, false, true, false); // 广播准时到达
                }
            }
        };
        try {
            ContextCompat.registerReceiver(ctx, holder[0],
                    new IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION),
                    ContextCompat.RECEIVER_NOT_EXPORTED);
            boolean started = wm.startScan();
            if (!started && hasCachedResults(wm)) {
                // 系统节流中，但有缓存结果可用：立即返回（cached 标记，JS 侧不推进"上次扫描"时间戳）
                if (done.compareAndSet(false, true)) {
                    try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                    resolveScan(pending, wm, true, false, false);
                }
                return;
            }
            // !started 且缓存也为空：不立即返回空列表（CN ROM 上会误报「未发现网络」），
            // 继续等广播；20s 超时后才回报空结果（started=false + timedOut=true，JS 侧给对应提示）
            // 20s 超时兜底走主线程 Handler：decor view 的 postDelayed 在视图脱离窗口时会丢回调，
            // 且 getActivity() 可能为 null（NPE 崩溃）
            if (getBridge() == null || getBridge().getActivity() == null) {
                // Activity 已销毁：没有可靠的广播兜底窗口，立即回退到已有结果
                if (done.compareAndSet(false, true)) {
                    try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                    resolveScan(pending, wm, true, started, true);
                }
                return;
            }
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                if (done.compareAndSet(false, true)) {
                    try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                    // 20s 未收到广播：结果可能是系统缓存，标记 cached + timedOut
                    resolveScan(pending, wm, true, started, true);
                }
            }, 20000);
        } catch (Exception e) {
            // 任何异常路径：先注销接收器（不留悬挂 receiver），再按类型 reject 且保证只结算一次
            if (done.compareAndSet(false, true)) {
                try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                if (e instanceof SecurityException) call.reject("需要 WiFi 权限", "PERM_DENIED");
                else call.reject("扫描失败", "SCAN_FAILED");
            }
        }
    }

    /** 系统缓存里是否已有扫描结果；取不到或抛异常一律按「无缓存」处理，交给广播/超时路径 */
    private boolean hasCachedResults(WifiManager wm) {
        try {
            List<ScanResult> results = wm.getScanResults();
            return results != null && !results.isEmpty();
        } catch (Exception e) {
            return false;
        }
    }

    private void resolveScan(PluginCall call, WifiManager wm, boolean cached, boolean started, boolean timedOut) {
        // 调用方（广播/节流/超时/异常路径）均已注销接收器，且 CAS 保证本方法只被调用一次
        try {
            List<ScanResult> results = wm.getScanResults();
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
            ret.put("cached", cached);
            ret.put("started", started);     // 系统是否真的执行了本次扫描
            ret.put("timedOut", timedOut);   // 是否等到超时才有结果（含一直没收到广播的空结果）
            call.resolve(ret);
        } catch (SecurityException e) {
            call.reject("需要 WiFi 权限", "PERM_DENIED");
        } catch (Exception e) {
            // 其它异常（部分 OEM ROM 的 getScanResults 抛出、结果构造异常等）统一归为 SCAN_FAILED
            call.reject("扫描失败", "SCAN_FAILED");
        }
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
        // 加密网络空密码会把网络当开放网络注册进系统，必须在构造 suggestion 之前拦下
        if (secured && (password == null || password.isEmpty())) {
            call.reject("该网络需要密码", "BAD_ARGS");
            return;
        }
        JSObject ret = new JSObject();
        if (Build.VERSION.SDK_INT >= 29) {
            int status;
            try {
                WifiNetworkSuggestion.Builder b = new WifiNetworkSuggestion.Builder().setSsid(ssid);
                if (secured && password != null && !password.isEmpty()) {
                    b.setWpa2Passphrase(password);
                }
                status = wm.addNetworkSuggestions(Collections.singletonList(b.build()));
            } catch (IllegalArgumentException e) {
                // Builder 对非法参数抛 IllegalArgumentException（setSsid 非法 unicode / setWpa2Passphrase 非 ASCII，
                // 系统服务校验失败也经 Binder 回抛）。若任其冒泡，Capacitor Bridge 会把它升级为主线程
                // RuntimeException 直接崩溃 App（Bridge.callPluginMethod 的 catch(Exception) 分支），故按业务失败返回
                ret.put("ok", false);
                ret.put("status", "BAD_ARGS");
                ret.put("error", "网络参数不受系统支持（请检查密码或 SSID 格式）");
                call.resolve(ret);
                return;
            } catch (SecurityException e) {
                call.reject("需要更改 WiFi 状态的权限", "PERM_DENIED");
                return;
            }
            if (status == WifiManager.STATUS_NETWORK_SUGGESTIONS_SUCCESS) {
                ret.put("ok", true);
                ret.put("status", "ADDED");
            } else if (status == WifiManager.STATUS_NETWORK_SUGGESTIONS_ERROR_ADD_DUPLICATE) {
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
}
