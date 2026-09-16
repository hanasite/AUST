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
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

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

    /** API 33+ 扫描只需 NEARBY_WIFI_DEVICES；更低版本仍走定位权限 */
    private String requiredPermissionAlias() {
        return Build.VERSION.SDK_INT >= 33 ? "nearbyWifi" : "fineLocation";
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
        // Capacitor 6：走注解式权限流（@PermissionCallback），调用由 Bridge 保存/回传
        requestPermissionForAlias(requiredPermissionAlias(), call, "permissionsCallback");
    }

    @PermissionCallback
    private void permissionsCallback(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("granted", hasPerm());
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
                    resolveScan(pending, wm, false);
                }
            }
        };
        ContextCompat.registerReceiver(ctx, holder[0],
                new IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        boolean started = wm.startScan();
        if (!started) {
            // 系统节流中：立即用缓存结果返回（带 cached 标记，JS 侧不推进"上次扫描"时间戳）
            if (done.compareAndSet(false, true)) {
                try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                resolveScan(pending, wm, true);
            }
            return;
        }
        getBridge().getActivity().getWindow().getDecorView().postDelayed(() -> {
            if (done.compareAndSet(false, true)) {
                try { ctx.unregisterReceiver(holder[0]); } catch (Exception ignored) {}
                resolveScan(pending, wm, true); // 12s 未收到广播：结果可能是系统缓存，标记 cached
            }
        }, 12000);
    }

    private void resolveScan(PluginCall call, WifiManager wm, boolean cached) {
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
        ret.put("cached", cached);
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
