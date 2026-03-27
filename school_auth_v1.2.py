"""
安徽理工大学 - 校园网自动认证工具 (AUST-ConnectEase)
版本 v1.2
新功能:
  - 整合校园网自助系统 (xgmm.aust.edu.cn)
  - 在线设备管理（查看 / 单台 / 全部下线）
  - 设备标签系统（预设 + 自定义，按 MAC 持久保存）
  - 当期流量 / （余额） / 时长 / 到期日期统计看板
  - 右侧可折叠面板，带蓝色边缘强调线
  - 窗口可调整大小，设备列表自动填充剩余空间
依赖: pip install requests          （必须）
      pip install ddddocr           （自助系统登录需要）
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import threading, json, os, re, sys, time

# ── requests ──────────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── ddddocr (可选) ────────────────────────────────────────────────────────────
# Pillow 10.0+ 移除了 ANTIALIAS，ddddocr 内部仍在使用，提前打补丁兼容
try:
    from PIL import Image as _pil_image
    if not hasattr(_pil_image, "ANTIALIAS"):
        _pil_image.ANTIALIAS = _pil_image.LANCZOS
except Exception:
    pass

try:
    import ddddocr as _ocr_mod
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".school_auth_config.json")

# ══════════════════════════════════════════════════════════════════════════════
#  开机自启动（Windows 注册表）
# ══════════════════════════════════════════════════════════════════════════════
APP_NAME = "AUST_ConnectEase"
RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_startup_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def is_startup_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except Exception:
        return False


def set_startup(enable: bool) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _get_startup_cmd())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except ImportError:
        return False
    except Exception as e:
        messagebox.showerror("自启动设置失败", str(e))
        return False


def is_windows() -> bool:
    return sys.platform.startswith("win")


# ══════════════════════════════════════════════════════════════════════════════
#  DrCOM 认证
# ══════════════════════════════════════════════════════════════════════════════
DRCOM_URL = "http://10.255.0.19/drcom/login"

ISP_MAP = {
    "电信  (@aust)":   "aust",
    "联通  (@unicom)": "unicom",
    "移动  (@cmcc)":   "cmcc",
    "教职工 (@jzg)":   "jzg",
}

NET_TYPE = ["宽带（POST）", "WiFi（GET）"]


def parse_drcom_response(text: str) -> dict:
    m = re.search(r'\((\{.*\})\)', text, re.DOTALL)
    if not m:
        return {"success": False, "error": f"无法解析响应: {text[:100]}"}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"success": False, "error": f"JSON解析失败: {text[:100]}"}

    result = data.get("result", -1)
    if result == 1:
        ip = data.get("v46ip", "")
        return {"success": True, "note": f"（IP: {ip}）" if ip else "", "data": data}
    if result == 0:
        msg = data.get("msg", "") or data.get("info", "") or data.get("err", "")
        if not msg:
            ecode = data.get("ecode", "")
            msg = {
                "E2553": "密码错误，请检查后重试",
                "E2901": "该账号已在线",
                "E2905": "账户欠费，请充值",
            }.get(str(ecode), f"认证失败 (code={ecode})")
        if "已在线" in msg or "online" in msg.lower():
            return {"success": True, "note": "（该账号已在线）"}
        return {"success": False, "error": msg}
    return {"success": False, "error": f"未知结果码 result={result}"}


def login_drcom(username: str, password: str, isp_suffix: str, net_type: str) -> dict:
    account = f"{username}@{isp_suffix}"
    params  = {"callback": "dr1003", "DDDDD": account, "upass": password, "0MKKey": "123456"}
    try:
        s    = requests.Session()
        resp = (s.post(DRCOM_URL, data=params, timeout=10)
                if net_type == "宽带（POST）"
                else s.get(DRCOM_URL, params=params, timeout=10))
        return parse_drcom_response(resp.text)
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "无法连接认证服务器 (10.255.0.19)\n请确认已接入校园网 WiFi / 有线"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "认证服务器超时，请重试"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  校园网自助系统 Portal API  (https://xgmm.aust.edu.cn)
# ══════════════════════════════════════════════════════════════════════════════
PORTAL_BASE   = "https://xgmm.aust.edu.cn"
PRESET_LABELS = [
    "PC/Mac 💻", "Windows 🖥", "Android 📱",
    "iPhone 🍎", "iPad 📲",   "路由器 📡", "其他",
]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0.0.0 Safari/537.36")


def portal_login(username: str, password: str) -> dict:
    """登录自助系统；需要 ddddocr。"""
    if not HAS_OCR:
        return {"success": False, "error": "OCR_MISSING"}

    sess = requests.Session()
    sess.headers.update({"User-Agent": _UA,
                          "Referer":    f"{PORTAL_BASE}/Self/login/",
                          "Origin":     PORTAL_BASE})
    try:
        r = sess.get(f"{PORTAL_BASE}/Self/login/", timeout=10)
        m = re.search(r'name="checkcode"\s+value="(\d+)"', r.text)
        if not m:
            return {"success": False, "error": "无法获取 checkcode，请检查网络"}

        img = sess.get(f"{PORTAL_BASE}/Self/login/randomCode?t={int(time.time()*1000)}",
                       timeout=10)
        # 兼容新旧版 ddddocr：新版支持 show_ad/beta，旧版不支持
        try:
            ocr = _ocr_mod.DdddOcr(show_ad=False, beta=True)
        except TypeError:
            try:
                ocr = _ocr_mod.DdddOcr(beta=True)
            except TypeError:
                ocr = _ocr_mod.DdddOcr()
        code = re.sub(r'[^a-zA-Z0-9]', '', ocr.classification(img.content)).upper()

        resp = sess.post(
            f"{PORTAL_BASE}/Self/login/verify",
            data={"foo": "", "bar": "", "checkcode": m.group(1),
                  "account": username, "password": password, "code": code},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False, timeout=10
        )
        if resp.status_code == 302 and "dashboard" in resp.headers.get("Location", ""):
            return {"success": True, "session": sess}
        return {"success": False, "error": "登录失败（验证码可能有误，可多试几次）"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "无法连接自助系统，请确认在校园网内"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _parse_dashboard_html(html: str) -> dict:
    d: dict = {"user_info": {}, "usage_stats": {}, "account_status": {}}
    for pat, keys, typ in [
        (r'<h4>(.*?)，\s*您好！',                                              ("user_info",     "name"),        str),
        (r'(\d+)\s*<small class="unit">\s*分钟\s*</small>.*?已用时长',         ("usage_stats",   "used_time_min"), int),
        (r'([\d\.]+)\s*<small class="unit">M</small>.*?已用流量',              ("usage_stats",   "used_flow_mb"), float),
        (r'([\d\.]+)\s*<small class="unit">\s*元\s*</small>.*?账户余额',       ("usage_stats",   "balance"),      float),
        (r'到期日期[：:]\s*</label>\s*<div.*?>\s*<span>\s*(\d{4}-\d{2}-\d{2})', ("account_status","expiry_date"),  str),
    ]:
        mo = re.search(pat, html, re.S)
        if mo:
            d[keys[0]][keys[1]] = typ(mo.group(1).strip())
    return d


def portal_get_dashboard(session) -> dict:
    try:
        r = session.get(f"{PORTAL_BASE}/Self/dashboard", timeout=10)
        if "login" in r.url.lower() or 'name="checkcode"' in r.text:
            return {"success": False, "error": "SESSION_EXPIRED"}
        return {"success": True, "data": _parse_dashboard_html(r.text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def portal_get_devices(session) -> dict:
    try:
        r = session.get(
            f"{PORTAL_BASE}/Self/dashboard/getOnlineList",
            params={"t": time.time(), "order": "asc", "_": int(time.time() * 1000)},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=10
        )
        if r.status_code == 200:
            return {"success": True, "devices": r.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "获取设备列表失败"}


def portal_offline_device(session, session_id: str, ip: str, mac: str) -> dict:
    try:
        mac_c = mac.replace("-", "").replace(":", "").upper()
        r = session.get(
            f"{PORTAL_BASE}/Self/dashboard/tooffline",
            params={"sessionid": session_id, "ip": ip, "mac": mac_c},
            timeout=10
        )
        if r.status_code == 200:
            res = r.json()
            return {"success": bool(res.get("success")), "error": res.get("msg", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "请求失败"}


def portal_logout(session) -> dict:
    try:
        r = session.get(f"{PORTAL_BASE}/Self/login/logout", timeout=10, allow_redirects=False)
        return {"success": r.status_code == 302}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  配置读写
# ══════════════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showwarning("保存失败", f"配置保存失败：{e}")


# ══════════════════════════════════════════════════════════════════════════════
#  GUI 主窗口
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    # ── 调色板 ────────────────────────────────────────────
    ACCENT    = "#2563EB"
    ACCENT_LT = "#BFDBFE"
    BG        = "#F0F4F8"
    CARD      = "#FFFFFF"
    GRAY      = "#9CA3AF"
    SUCCESS   = "#059669"
    WARN      = "#D97706"
    DANGER    = "#DC2626"

    FONT   = ("Microsoft YaHei", 10)
    FONT_H = ("Microsoft YaHei", 11, "bold")
    FONT_S = ("Microsoft YaHei", 9)
    FONT_M = ("Microsoft YaHei", 8)

    def __init__(self):
        super().__init__()
        self.title("AUST 校园认证助手 v1.2")
        # 设置窗口初始大小并允许用户调整
        self.geometry("900x750")
        self.resizable(True, True)
        self.configure(bg=self.BG)

        # 状态
        self._portal_session  = None
        self._devices: list   = []
        self._device_labels: dict = {}
        self._portal_expanded = True

        self._build_ui()
        self._load_saved()

    # ══════════════════════════════════════════════════════
    #  顶层布局
    # ══════════════════════════════════════════════════════
    def _build_ui(self):
        self._build_header()
        main = tk.Frame(self, bg=self.BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)

        left = tk.Frame(main, bg=self.BG)
        left.pack(side="left", fill="both", expand=False, padx=(0, 14))

        right = tk.Frame(main, bg=self.BG, width=310)
        right.pack(side="right", fill="both", expand=True)
        right.pack_propagate(False)

        self._build_left(left)
        self._build_right(right)

    def _build_header(self):
        h = tk.Frame(self, bg=self.ACCENT, pady=14)
        h.pack(fill="x")
        tk.Label(h, text="🏫  AUST 校园认证助手",
                 bg=self.ACCENT, fg="white",
                 font=("Microsoft YaHei", 14, "bold")).pack()
        tk.Label(h, text="安徽理工大学  •  教务系统 & 校园网一键认证",
                 bg=self.ACCENT, fg=self.ACCENT_LT,
                 font=self.FONT_S).pack(pady=(2, 0))

    def _card(self, parent, title: str) -> tk.LabelFrame:
        return tk.LabelFrame(
            parent, text=title, bg=self.CARD, font=self.FONT_H,
            fg="#1E3A5F", relief="flat", bd=0,
            highlightthickness=1, highlightbackground="#D1D5DB",
            padx=14, pady=10
        )

    # ══════════════════════════════════════════════════════
    #  左侧：账号 / 网络 / 教务 / 认证按钮
    # ══════════════════════════════════════════════════════
    def _build_left(self, parent):
        self._build_account_card(parent)
        self._build_network_card(parent)
        self._build_jwgl_card(parent)
        self._build_auth_btn(parent)

    def _build_account_card(self, parent):
        card = self._card(parent, "👤  账号信息")
        card.pack(fill="x", pady=(0, 10))
        for i, (label, attr, pwd) in enumerate([
            ("学号 / 工号", "_username", False),
            ("密       码", "_password", True),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=i, column=0, padx=8, pady=6)
            var = tk.StringVar()
            setattr(self, attr, var)
            tk.Entry(card, textvariable=var, show="*" if pwd else "",
                     font=self.FONT, width=22, relief="solid", bd=1
                     ).grid(row=i, column=1, padx=8, pady=6, sticky="w")

    def _build_network_card(self, parent):
        card = self._card(parent, "🌐  校园网设置")
        card.pack(fill="x", pady=(0, 10))

        tk.Label(card, text="运营商", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=0, column=0, padx=8, pady=5)
        self._isp_var = tk.StringVar(value=list(ISP_MAP.keys())[0])
        ttk.Combobox(card, textvariable=self._isp_var, values=list(ISP_MAP.keys()),
                     state="readonly", width=16, font=self.FONT
                     ).grid(row=0, column=1, padx=8, pady=5, sticky="w")

        tk.Label(card, text="网络类型", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=1, column=0, padx=8, pady=5)
        self._net_type_var = tk.StringVar(value=NET_TYPE[0])
        ttk.Combobox(card, textvariable=self._net_type_var, values=NET_TYPE,
                     state="readonly", width=16, font=self.FONT
                     ).grid(row=1, column=1, padx=8, pady=5, sticky="w")

        tk.Label(card, text="账号预览", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=2, column=0, padx=8, pady=4)
        self._preview_var = tk.StringVar()
        tk.Label(card, textvariable=self._preview_var, bg=self.CARD,
                 fg=self.GRAY, font=("Consolas", 9)
                 ).grid(row=2, column=1, padx=8, pady=4, sticky="w")

        self._username.trace_add("write", self._update_preview)
        self._isp_var.trace_add("write",  self._update_preview)
        self._update_preview()

    def _build_jwgl_card(self, parent):
        card = self._card(parent, "📚  教务系统登录")
        card.pack(fill="x", pady=(0, 10))
        for i, (label, ph) in enumerate([
            ("学号 / 工号", "与校园网账号相同"),
            ("密       码", "待完善功能"),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=i, column=0, padx=8, pady=5)
            e = tk.Entry(card, font=self.FONT, width=22, relief="solid", bd=1,
                         bg="#F3F4F6", fg=self.GRAY, state="disabled",
                         disabledforeground=self.GRAY, disabledbackground="#F3F4F6")
            e.grid(row=i, column=1, padx=8, pady=5, sticky="w")
            e.config(state="normal"); e.insert(0, ph); e.config(state="disabled")
        tk.Label(card, text="⚙️  功能开发中，敬请期待",
                 bg="#FEF3C7", fg="#92400E", font=self.FONT_M,
                 padx=8, pady=3
                 ).grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 2), sticky="w")

    def _build_auth_btn(self, parent):
        self._btn = tk.Button(
            parent, text="🚀  一键认证",
            bg=self.ACCENT, fg="white",
            font=("Microsoft YaHei", 11, "bold"),
            relief="flat", cursor="hand2",
            padx=12, pady=9, command=self._start
        )
        self._btn.pack(fill="x", pady=(4, 0))

    # ══════════════════════════════════════════════════════
    #  右侧：控件行 + 状态卡 + 折叠自助面板
    # ══════════════════════════════════════════════════════
    def _build_right(self, parent):
        # 控件行
        top = tk.Frame(parent, bg=self.BG)
        top.pack(fill="x", pady=(0, 10))

        tk.Button(top, text="🎨 背景色",
                  bg="#E5E7EB", fg="#1F2937", font=self.FONT_S,
                  relief="flat", cursor="hand2",
                  command=self._choose_bg_color).pack(side="left", padx=(0, 8))

        cb_f = tk.Frame(top, bg=self.BG)
        cb_f.pack(side="left", fill="x", expand=True)

        self._save_var    = tk.BooleanVar(value=True)
        self._do_net_var  = tk.BooleanVar(value=True)
        self._startup_var = tk.BooleanVar(value=is_startup_enabled())

        for text, var, cmd in [
            ("💾 保存配置",  self._save_var,    None),
            ("📡 认证校园网", self._do_net_var,  None),
            ("🔄 开机自启动", self._startup_var, self._on_startup_toggle),
        ]:
            tk.Checkbutton(cb_f, text=text, variable=var, bg=self.BG,
                           font=self.FONT_S, command=cmd).pack(anchor="w")

        if not is_windows():
            self._startup_var.set(False)
            for w in cb_f.winfo_children():
                if isinstance(w, tk.Checkbutton) and "自启动" in str(w.cget("text")):
                    w.config(state="disabled", fg=self.GRAY)
            tk.Label(cb_f, text="  ⚠ 自启动仅支持 Windows",
                     bg=self.BG, fg=self.GRAY, font=self.FONT_M).pack(anchor="w", padx=4)

        # DrCOM 状态卡
        self._build_status_card(parent)

        # 折叠自助系统面板
        self._build_portal_panel(parent)

    # ── DrCOM 状态卡 ──────────────────────────────────────
    def _build_status_card(self, parent):
        card = tk.Frame(parent, bg=self.CARD,
                        highlightthickness=1, highlightbackground="#D1D5DB",
                        padx=12, pady=10)
        card.pack(fill="x", pady=(0, 10))
        tk.Label(card, text="认证状态", bg=self.CARD, fg=self.GRAY,
                 font=("Microsoft YaHei", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._net_status  = self._status_row(card, "DrCOM")
        self._jwgl_status = self._status_row(card, "教务系统")
        tk.Frame(card, bg="#E5E7EB", height=1).pack(fill="x", pady=5)
        self._log = tk.Text(card, height=4, width=34, state="disabled",
                            bg="#F9FAFB", relief="flat",
                            font=("Consolas", 8), fg="#374151", wrap="word")
        self._log.pack(fill="x")

    def _status_row(self, parent, label: str) -> tk.StringVar:
        f = tk.Frame(parent, bg=self.CARD)
        f.pack(anchor="w", pady=1)
        tk.Label(f, text=f"{label}：", bg=self.CARD,
                 font=self.FONT_S, width=10, anchor="w").pack(side="left")
        var = tk.StringVar(value="⬜ 未认证")
        tk.Label(f, textvariable=var, bg=self.CARD, font=self.FONT_S).pack(side="left")
        return var

    # ══════════════════════════════════════════════════════
    #  折叠自助系统面板
    # ══════════════════════════════════════════════════════
    def _build_portal_panel(self, parent):
        """右侧可折叠面板，展开时左侧有 3px 蓝色强调边。"""
        wrapper = tk.Frame(parent, bg=self.BG)
        wrapper.pack(fill="both", expand=True)

        # ── 折叠按钮（整行，accent 色背景） ──
        self._portal_toggle_btn = tk.Button(
            wrapper,
            text="▼  📊 校园网自助系统",
            bg=self.ACCENT, fg="white",
            font=("Microsoft YaHei", 9, "bold"),
            relief="flat", cursor="hand2",
            anchor="w", padx=10, pady=7,
            command=self._toggle_portal
        )
        self._portal_toggle_btn.pack(fill="x")

        # ── 内容容器（accent 左边框 + 白色主体） ──
        self._portal_outer = tk.Frame(wrapper, bg=self.BG)
        self._portal_outer.pack(fill="both", expand=True)

        # 3 px 蓝色竖条
        tk.Frame(self._portal_outer, bg=self.ACCENT, width=3).pack(side="left", fill="y")

        # 主体内容
        self._portal_body = tk.Frame(
            self._portal_outer, bg=self.CARD,
            highlightthickness=1, highlightbackground=self.ACCENT_LT,
            padx=10, pady=10
        )
        self._portal_body.pack(side="left", fill="both", expand=True)

        self._build_portal_content(self._portal_body)

    def _toggle_portal(self):
        self._portal_expanded = not self._portal_expanded
        if self._portal_expanded:
            self._portal_outer.pack(fill="both", expand=True)
            self._portal_toggle_btn.config(text="▼  📊 校园网自助系统",
                                           bg=self.ACCENT, fg="white")
        else:
            self._portal_outer.pack_forget()
            self._portal_toggle_btn.config(text="▶  📊 校园网自助系统",
                                           bg="#DBEAFE", fg=self.ACCENT)

    # ── 面板内容 ──────────────────────────────────────────
    def _build_portal_content(self, parent):

        # ── 1. 顶部控制行 ──────────────────────────────────
        ctrl = tk.Frame(parent, bg=self.CARD)
        ctrl.pack(fill="x", pady=(0, 6))

        self._portal_status_var = tk.StringVar(value="● 未连接")
        self._portal_status_lbl = tk.Label(
            ctrl, textvariable=self._portal_status_var,
            bg=self.CARD, fg=self.GRAY, font=self.FONT_S
        )
        self._portal_status_lbl.pack(side="left")

        btn_row = tk.Frame(ctrl, bg=self.CARD)
        btn_row.pack(side="right")

        self._portal_login_btn = tk.Button(
            btn_row, text="登 录",
            bg=self.ACCENT, fg="white", font=self.FONT_S,
            relief="flat", cursor="hand2", padx=8, pady=3,
            command=self._portal_do_login
        )
        self._portal_login_btn.pack(side="left", padx=(0, 4))

        self._portal_refresh_btn = tk.Button(
            btn_row, text="🔄", bg="#E5E7EB", fg="#374151",
            font=self.FONT_S, relief="flat", cursor="hand2",
            padx=5, pady=3, command=self._portal_do_refresh,
            state="disabled"
        )
        self._portal_refresh_btn.pack(side="left", padx=(0, 4))

        self._portal_logout_btn = tk.Button(
            btn_row, text="注 销",
            bg="#FEE2E2", fg=self.DANGER, font=self.FONT_S,
            relief="flat", cursor="hand2", padx=6, pady=3,
            command=self._portal_do_logout, state="disabled"
        )
        self._portal_logout_btn.pack(side="left")

        # OCR 缺失提示条
        if not HAS_OCR:
            warn = tk.Frame(parent, bg="#FEF3C7",
                            highlightthickness=1, highlightbackground="#FDE68A")
            warn.pack(fill="x", pady=(0, 6))
            tk.Label(warn, text="⚠ 需安装 ddddocr 才能登录自助系统",
                     bg="#FEF3C7", fg="#92400E", font=self.FONT_M,
                     padx=6, pady=3).pack(side="left")
            tk.Button(warn, text="一键安装",
                      bg="#F59E0B", fg="white", font=self.FONT_M,
                      relief="flat", cursor="hand2", padx=5,
                      command=self._install_ddddocr
                      ).pack(side="right", padx=4, pady=2)

        # ── 2. 统计卡片行 ──────────────────────────────────
        tk.Frame(parent, bg="#E5E7EB", height=1).pack(fill="x", pady=(0, 6))

        stats_f = tk.Frame(parent, bg=self.CARD)
        stats_f.pack(fill="x", pady=(0, 6))
        stats_f.columnconfigure((0, 1, 2), weight=1)

        self._stat_vars: dict = {}
        stat_defs = [
            #("balance", "余  额",   "¥ --",   "💰"),  没有意义都是0
            ("flow",    "当期流量", "-- MB",  "📊"),
            ("time",    "已用时长", "-- min", "⏱"),
            ("expiry",  "到期日期", "----",   "📅"),
        ]
        for col, (key, label, default, icon) in enumerate(stat_defs):
            cell = tk.Frame(stats_f, bg="#F8FAFC",
                            highlightthickness=1, highlightbackground="#E2E8F0",
                            padx=4, pady=4)
            cell.grid(row=0, column=col, padx=2, sticky="nsew")
            tk.Label(cell, text=icon, bg="#F8FAFC",
                     font=("", 12)).pack()
            var = tk.StringVar(value=default)
            self._stat_vars[key] = var
            tk.Label(cell, textvariable=var, bg="#F8FAFC",
                     font=("Microsoft YaHei", 8, "bold"),
                     fg="#1E3A5F", wraplength=62).pack()
            tk.Label(cell, text=label, bg="#F8FAFC",
                     fg=self.GRAY, font=self.FONT_M).pack()

        # ── 3. 设备列表区 ──────────────────────────────────
        tk.Frame(parent, bg="#E5E7EB", height=1).pack(fill="x", pady=(2, 6))

        dev_hdr = tk.Frame(parent, bg=self.CARD)
        dev_hdr.pack(fill="x", pady=(0, 4))

        self._device_count_var = tk.StringVar(value="📱 在线设备")
        tk.Label(dev_hdr, textvariable=self._device_count_var,
                 bg=self.CARD, fg="#1E3A5F",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")

        self._offline_all_btn = tk.Button(
            dev_hdr, text="全部下线",
            bg="#FEE2E2", fg=self.DANGER, font=self.FONT_M,
            relief="flat", cursor="hand2", padx=7, pady=2,
            command=self._portal_offline_all, state="disabled"
        )
        self._offline_all_btn.pack(side="right")

        # 可滚动设备列表（Canvas 高度不固定，自动填充剩余空间）
        list_outer = tk.Frame(parent, bg="#F1F5F9",
                              highlightthickness=1, highlightbackground="#CBD5E1")
        list_outer.pack(fill="both", expand=True)

        self._dev_canvas = tk.Canvas(
            list_outer, bg="#F1F5F9",
            highlightthickness=0          # 移除固定高度，让 Canvas 自然填充
        )
        dev_sb = ttk.Scrollbar(list_outer, orient="vertical",
                               command=self._dev_canvas.yview)
        self._dev_list_frame = tk.Frame(self._dev_canvas, bg="#F1F5F9")
        self._dev_list_frame.bind(
            "<Configure>",
            lambda e: self._dev_canvas.configure(
                scrollregion=self._dev_canvas.bbox("all"))
        )
        self._dev_canvas.create_window((0, 0), window=self._dev_list_frame, anchor="nw")
        self._dev_canvas.configure(yscrollcommand=dev_sb.set)
        self._dev_canvas.pack(side="left", fill="both", expand=True)
        dev_sb.pack(side="right", fill="y")
        self._dev_canvas.bind(
            "<MouseWheel>",
            lambda e: self._dev_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        )

        # 初始空状态
        tk.Label(self._dev_list_frame, text="暂无在线设备",
                 bg="#F1F5F9", fg=self.GRAY, font=self.FONT_S).pack(pady=20)

    # ══════════════════════════════════════════════════════
    #  Portal 业务逻辑
    # ══════════════════════════════════════════════════════
    def _portal_do_login(self):
        u = self._username.get().strip()
        p = self._password.get().strip()
        if not u or not p:
            messagebox.showwarning("提示", "请先在左侧填写账号和密码")
            return
        self._portal_login_btn.config(state="disabled", text="登录中…")
        self._portal_status_var.set("⏳ 登录中…")
        self._portal_status_lbl.config(fg=self.WARN)
        threading.Thread(target=self._portal_login_thread,
                         args=(u, p), daemon=True).start()

    def _portal_login_thread(self, u, p):
        r = portal_login(u, p)

        def done():
            self._portal_login_btn.config(state="normal", text="登 录")
            if r["success"]:
                self._portal_session = r["session"]
                self._portal_status_var.set("● 已连接")
                self._portal_status_lbl.config(fg=self.SUCCESS)
                self._portal_refresh_btn.config(state="normal")
                self._portal_logout_btn.config(state="normal")
                self._log_msg("✅ 自助系统登录成功")
                self._portal_do_refresh()
            elif r["error"] == "OCR_MISSING":
                self._portal_status_var.set("● 缺少 ddddocr")
                self._portal_status_lbl.config(fg=self.DANGER)
            else:
                self._portal_status_var.set("● 登录失败")
                self._portal_status_lbl.config(fg=self.DANGER)
                self._log_msg(f"❌ 自助系统：{r['error']}")

        self.after(0, done)

    def _portal_do_refresh(self):
        if not self._portal_session:
            messagebox.showinfo("提示", "请先登录自助系统")
            return
        self._portal_refresh_btn.config(state="disabled")
        threading.Thread(target=self._portal_refresh_thread, daemon=True).start()

    def _portal_refresh_thread(self):
        dash_r = portal_get_dashboard(self._portal_session)
        dev_r  = portal_get_devices(self._portal_session)

        def done():
            self._portal_refresh_btn.config(state="normal")

            if dash_r["success"]:
                stats = dash_r["data"].get("usage_stats", {})
                acct  = dash_r["data"].get("account_status", {})
                bal   = stats.get("balance")
                #self._stat_vars["balance"].set(f"¥ {bal}" if bal is not None else "¥ --")  没有意义
                flow_mb = stats.get("used_flow_mb")
                if flow_mb is not None:
                    flow_str = (f"{flow_mb/1024:.2f} GB"
                                if flow_mb >= 1024 else f"{int(flow_mb)} MB")
                    self._stat_vars["flow"].set(flow_str)
                t_min = stats.get("used_time_min")
                self._stat_vars["time"].set(f"{t_min} min" if t_min is not None else "-- min")
                self._stat_vars["expiry"].set(acct.get("expiry_date", "----"))

            elif dash_r.get("error") == "SESSION_EXPIRED":
                self._portal_session = None
                self._portal_status_var.set("● 会话过期")
                self._portal_status_lbl.config(fg=self.DANGER)
                self._portal_refresh_btn.config(state="disabled")
                self._portal_logout_btn.config(state="disabled")
                return

            if dev_r["success"]:
                self._devices = dev_r["devices"]
            else:
                self._devices = []

            self._rebuild_device_list()

        self.after(0, done)

    def _portal_do_logout(self):
        if self._portal_session:
            threading.Thread(
                target=lambda: portal_logout(self._portal_session),
                daemon=True
            ).start()
        self._portal_session = None
        self._devices = []
        self._portal_status_var.set("● 未连接")
        self._portal_status_lbl.config(fg=self.GRAY)
        self._portal_refresh_btn.config(state="disabled")
        self._portal_logout_btn.config(state="disabled")
        self._rebuild_device_list()
        self._log_msg("🔒 已注销自助系统")

    def _portal_offline_all(self):
        if not self._devices:
            return
        if not messagebox.askyesno("确认操作",
                                   f"确定要下线全部 {len(self._devices)} 台设备吗？"):
            return
        self._offline_all_btn.config(state="disabled")
        threading.Thread(target=self._offline_all_thread, daemon=True).start()

    def _offline_all_thread(self):
        ok = 0
        total = len(self._devices)
        for d in list(self._devices):
            r = portal_offline_device(
                self._portal_session,
                d.get("sessionId"), d.get("ip"), d.get("mac")
            )
            if r["success"]:
                ok += 1
            time.sleep(0.8)

        def done():
            self._log_msg(f"📴 已下线 {ok}/{total} 台设备")
            self._portal_do_refresh()

        self.after(0, done)

    def _portal_offline_one(self, device: dict, btn: tk.Button):
        btn.config(state="disabled")

        def worker():
            r = portal_offline_device(
                self._portal_session,
                device.get("sessionId"), device.get("ip"), device.get("mac")
            )

            def done():
                if r["success"]:
                    self._log_msg(f"📴 {device.get('ip')} 已下线")
                    self._portal_do_refresh()
                else:
                    self._log_msg(f"❌ 下线失败: {r.get('error', '')}")
                    btn.config(state="normal")

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════
    #  设备列表渲染
    # ══════════════════════════════════════════════════════
    def _rebuild_device_list(self):
        # ---------- 新增：设备去重（以IP为键） ----------
        seen_ips = set()
        unique_devices = []
        for d in self._devices:
            ip = d.get("ip")
            if ip and ip not in seen_ips:
                seen_ips.add(ip)
                unique_devices.append(d)
            # 如果IP为空，保留（但一般不会为空）
            elif not ip and d not in unique_devices:
                unique_devices.append(d)
        self._devices = unique_devices
        # -----------------------------------------------

        for w in self._dev_list_frame.winfo_children():
            w.destroy()

        if not self._devices:
            tk.Label(self._dev_list_frame, text="暂无在线设备",
                     bg="#F1F5F9", fg=self.GRAY, font=self.FONT_S).pack(pady=20)
            self._device_count_var.set("📱 在线设备（0台）")
            self._offline_all_btn.config(state="disabled")
            return

        n = len(self._devices)
        self._device_count_var.set(f"📱 在线设备（{n} 台）")
        self._offline_all_btn.config(state="normal")

        for idx, device in enumerate(self._devices):
            self._build_device_row(idx, device)
            if idx < n - 1:
                tk.Frame(self._dev_list_frame, bg="#E2E8F0", height=1).pack(fill="x")

        self._dev_list_frame.update_idletasks()
        self._dev_canvas.configure(
            scrollregion=self._dev_canvas.bbox("all"),
            width=self._portal_body.winfo_width() - 40
        )

    def _build_device_row(self, idx: int, device: dict):
        mac = device.get("mac", "")
        ip  = device.get("ip", "N/A")
        row_bg = self.CARD if idx % 2 == 0 else "#F8FAFC"

        row = tk.Frame(self._dev_list_frame, bg=row_bg, pady=5, padx=8)
        row.pack(fill="x")

        # 第一行：类型徽章 + IP + 流量 + 下线按钮
        line1 = tk.Frame(row, bg=row_bg)
        line1.pack(fill="x")

        badge_text, badge_bg = self._terminal_badge(device.get("terminalType", ""))
        tk.Label(line1, text=badge_text, bg=badge_bg, fg="white",
                 font=self.FONT_M, padx=4, pady=1).pack(side="left", padx=(0, 5))

        tk.Label(line1, text=ip, bg=row_bg,
                 font=("Consolas", 9, "bold"), fg="#1E3A5F").pack(side="left")

        flow_mb = float(device.get("downFlow", 0)) / 1024
        tk.Label(line1, text=f"  ↓{flow_mb:.1f}MB",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_M).pack(side="left")

        offline_btn = tk.Button(
            line1, text="下 线",
            bg="#FEE2E2", fg=self.DANGER, font=self.FONT_M,
            relief="flat", cursor="hand2", padx=5, pady=1
        )
        offline_btn.config(
            command=lambda d=device, b=offline_btn: self._portal_offline_one(d, b)
        )
        offline_btn.pack(side="right")

        # 第二行：上线时长 + 标签选择器
        line2 = tk.Frame(row, bg=row_bg)
        line2.pack(fill="x", pady=(3, 0))

        use_time = device.get("useTime", "--")
        tk.Label(line2, text=f"⏱ {use_time}min",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_M).pack(side="left")

        tk.Label(line2, text=" 标签:",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_M).pack(side="left")

        label_var = tk.StringVar(value=self._device_labels.get(mac, ""))
        combo = ttk.Combobox(
            line2, textvariable=label_var,
            values=PRESET_LABELS, width=14, font=self.FONT_M
        )
        combo.pack(side="left", padx=(2, 0))

        def _on_label(*_, _mac=mac, _var=label_var):
            self._device_labels[_mac] = _var.get()
            self._save_device_labels()

        label_var.trace_add("write", _on_label)

    @staticmethod
    def _terminal_badge(term_type: str) -> tuple:
        t = str(term_type).lower()
        if "windows" in t or "pc" in t:  return "🖥 PC",      "#6366F1"
        if "android" in t:               return "📱 Android", "#10B981"
        if "iphone" in t or "ios" in t:  return "🍎 iPhone",  "#6B7280"
        if "ipad" in t:                  return "📲 iPad",     "#8B5CF6"
        if "mac" in t:                   return "💻 Mac",      "#7C3AED"
        if "router" in t or "路由" in t: return "📡 路由",     "#F59E0B"
        return "📟 未知", "#94A3B8"

    def _save_device_labels(self):
        cfg = load_config()
        cfg["device_labels"] = self._device_labels
        save_config(cfg)

    def _install_ddddocr(self):
        self._log_msg("⏳ 正在安装 ddddocr，请稍候…")

        def worker():
            try:
                import subprocess as sp
                # 使用清华源（可替换为其他国内源）
                sp.check_call([
                    sys.executable, "-m", "pip", "install",
                    "ddddocr",
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
                ])
                self.after(0, lambda: self._log_msg("✅ ddddocr 安装成功，请重启程序"))
            except Exception as e:
                self.after(0, lambda: self._log_msg(f"❌ 安装失败: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════
    #  公共辅助
    # ══════════════════════════════════════════════════════
    def _update_preview(self, *_):
        uid    = self._username.get().strip() or "学号"
        suffix = ISP_MAP.get(self._isp_var.get(), "aust")
        self._preview_var.set(f"{uid}@{suffix}")

    def _choose_bg_color(self):
        color = colorchooser.askcolor(title="选择背景颜色", initialcolor=self.BG)[1]
        if color:
            self.BG = color
            self._apply_bg_recursive(self)
            self._log_msg(f"🎨 背景色已更改为 {color}")

    _SKIP_BG = frozenset({
        "#FFFFFF", "#2563EB", "#DBEAFE", "#FEF3C7", "#F8FAFC",
        "#F1F5F9", "#F3F4F6", "#FEE2E2", "#F9FAFB",
    })

    def _apply_bg_recursive(self, widget):
        try:
            bg = widget.cget("bg")
            if bg not in self._SKIP_BG:
                widget.configure(bg=self.BG)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._apply_bg_recursive(child)

    def _on_startup_toggle(self):
        enable = self._startup_var.get()
        ok = set_startup(enable)
        if ok:
            self._log_msg(f"🔄 开机自启动{'已开启' if enable else '已关闭'}")
        else:
            self._startup_var.set(not enable)

    def _load_saved(self):
        cfg = load_config()
        if cfg.get("username"):  self._username.set(cfg["username"])
        if cfg.get("password"):  self._password.set(cfg["password"])
        if cfg.get("isp") and cfg["isp"] in ISP_MAP:
            self._isp_var.set(cfg["isp"])
        if cfg.get("net_type") and cfg["net_type"] in NET_TYPE:
            self._net_type_var.set(cfg["net_type"])
        if cfg.get("do_net") is not None:
            self._do_net_var.set(cfg["do_net"])
        self._device_labels = cfg.get("device_labels", {})

    # ── DrCOM 认证流程 ────────────────────────────────────
    def _start(self):
        username = self._username.get().strip()
        password = self._password.get().strip()
        isp_key  = self._isp_var.get()
        net_type = self._net_type_var.get()

        if not username or not password:
            messagebox.showwarning("提示", "请填写学号和密码")
            return

        if self._save_var.get():
            cfg = load_config()
            cfg.update({
                "username": username, "password": password,
                "isp": isp_key, "net_type": net_type,
                "do_net": self._do_net_var.get(),
            })
            save_config(cfg)
            self._log_msg("💾 配置已保存")

        self._btn.config(state="disabled", text="认证中…")
        self._net_status.set("⏳ 认证中…")
        self._jwgl_status.set("⚙️ 待完善")

        isp_suffix = ISP_MAP.get(isp_key, "aust")
        threading.Thread(
            target=self._run_auth,
            args=(username, password, isp_suffix, net_type),
            daemon=True
        ).start()

    def _run_auth(self, username, password, isp_suffix, net_type):
        if self._do_net_var.get():
            self._log_msg(f"→ 校园网认证  {username}@{isp_suffix}  [{net_type}]")
            r = login_drcom(username, password, isp_suffix, net_type)
            if r["success"]:
                note = r.get("note", "")
                self._net_status.set(f"✅ 认证成功 {note}".strip())
                self._log_msg(f"✅ 校园网认证成功 {note}".strip())
            else:
                self._net_status.set("❌ 认证失败")
                self._log_msg(f"❌ 校园网：{r['error']}")
        else:
            self._net_status.set("⬛ 已跳过")
        self.after(0, lambda: self._btn.config(state="normal", text="🚀  一键认证"))

    def _log_msg(self, msg: str):
        def _update():
            self._log.config(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.config(state="disabled")
        self.after(0, _update)


if __name__ == "__main__":
    app = App()
    app.mainloop()