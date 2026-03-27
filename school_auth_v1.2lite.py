"""
安徽理工大学 - 校园网自动认证工具 (AUST-ConnectEase)
版本 v1.2lite
变更:
  - 移除 ddddocr 依赖，改为手动输入验证码弹窗（含图片预览 & 一键刷新）
  - 优化整体 UI：更紧凑的卡片、优化字重/间距、状态徽章样式
  - 验证码弹窗支持 Pillow（可选）自动放大显示，无 Pillow 时显示提示并可在浏览器打开
依赖: pip install requests          （必须）
      pip install Pillow             （可选，用于验证码图片显示，强烈推荐）
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import threading, json, os, re, sys, time, webbrowser, tempfile

# ── requests ──────────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── Pillow（可选，用于验证码图片显示） ────────────────────────────────────────
try:
    from PIL import Image as _PilImage, ImageTk as _PilImageTk
    import io as _io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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


def portal_login(username: str, password: str, captcha_fn) -> dict:
    """
    登录自助系统。
    captcha_fn(session, base_url) -> str | None
        由调用方提供，负责展示验证码图片并返回用户输入的文字。
        返回 None 表示用户取消。
    """
    sess = requests.Session()
    sess.headers.update({"User-Agent": _UA,
                          "Referer":    f"{PORTAL_BASE}/Self/login/",
                          "Origin":     PORTAL_BASE})
    try:
        r = sess.get(f"{PORTAL_BASE}/Self/login/", timeout=10)
        m = re.search(r'name="checkcode"\s+value="(\d+)"', r.text)
        if not m:
            return {"success": False, "error": "无法获取 checkcode，请检查网络"}

        checkcode = m.group(1)

        # 获取验证码图片
        img_resp = sess.get(
            f"{PORTAL_BASE}/Self/login/randomCode?t={int(time.time()*1000)}",
            timeout=10
        )

        # 调用 UI 侧函数让用户输入
        code = captcha_fn(sess, img_resp.content)
        if code is None:
            return {"success": False, "error": "用户取消"}

        code = re.sub(r'[^a-zA-Z0-9]', '', code).upper()
        if not code:
            return {"success": False, "error": "验证码为空"}

        resp = sess.post(
            f"{PORTAL_BASE}/Self/login/verify",
            data={"foo": "", "bar": "", "checkcode": checkcode,
                  "account": username, "password": password, "code": code},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False, timeout=10
        )
        if resp.status_code == 302 and "dashboard" in resp.headers.get("Location", ""):
            return {"success": True, "session": sess}
        return {"success": False, "error": "登录失败（验证码有误？可重试）"}
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
#  验证码弹窗
# ══════════════════════════════════════════════════════════════════════════════
class CaptchaDialog(tk.Toplevel):
    """
    显示验证码图片，让用户手动输入识别结果。
    使用方式：
        dlg = CaptchaDialog(parent, session, img_bytes)
        parent.wait_window(dlg)
        code = dlg.result   # None 表示取消
    """

    # 调色 - 与主窗口保持一致
    ACCENT  = "#2563EB"
    BG      = "#F8FAFC"
    CARD    = "#FFFFFF"
    DANGER  = "#DC2626"
    GRAY    = "#6B7280"

    FONT    = ("Microsoft YaHei", 10)
    FONT_H  = ("Microsoft YaHei", 11, "bold")
    FONT_S  = ("Microsoft YaHei", 9)

    def __init__(self, parent, session, img_bytes: bytes):
        super().__init__(parent)
        self.title("验证码")
        self.resizable(False, False)
        self.configure(bg=self.BG)
        self.grab_set()   # 模态
        self.focus_set()

        self.result: str | None = None
        self._session   = session
        self._photo_ref = None   # 防止 GC 回收 PhotoImage

        # ── 标题栏 ─────────────────────────────────────────
        hdr = tk.Frame(self, bg=self.ACCENT, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔐  请输入验证码",
                 bg=self.ACCENT, fg="white",
                 font=self.FONT_H).pack()

        # ── 主体 ───────────────────────────────────────────
        body = tk.Frame(self, bg=self.BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # 图片区
        img_card = tk.Frame(body, bg=self.CARD,
                            highlightthickness=1,
                            highlightbackground="#E2E8F0",
                            padx=12, pady=10)
        img_card.pack(pady=(0, 14))

        self._img_label = tk.Label(img_card, bg=self.CARD)
        self._img_label.pack()

        self._load_image(img_bytes)

        # 刷新按钮（放在图片卡片下方，小号）
        tk.Button(
            body, text="↻  换一张验证码",
            bg="#EFF6FF", fg=self.ACCENT,
            font=self.FONT_S, relief="flat",
            cursor="hand2", padx=8, pady=3,
            command=self._refresh_captcha
        ).pack(pady=(0, 12))

        # 输入框
        input_row = tk.Frame(body, bg=self.BG)
        input_row.pack(fill="x", pady=(0, 16))
        tk.Label(input_row, text="验证码：",
                 bg=self.BG, font=self.FONT, width=6, anchor="e").pack(side="left")
        self._code_var = tk.StringVar()
        self._entry = tk.Entry(
            input_row, textvariable=self._code_var,
            font=("Consolas", 13, "bold"),
            width=10, relief="solid", bd=1,
            justify="center"
        )
        self._entry.pack(side="left", padx=(4, 0))
        self._entry.focus_set()

        # 提示文字
        if not HAS_PIL:
            tk.Label(
                body,
                text="⚠ 未安装 Pillow，图片可能无法显示\n  pip install Pillow",
                bg="#FEF3C7", fg="#92400E",
                font=("Microsoft YaHei", 8),
                padx=8, pady=4, justify="left"
            ).pack(fill="x", pady=(0, 10))

        # 按钮行
        btn_row = tk.Frame(body, bg=self.BG)
        btn_row.pack(fill="x")
        tk.Button(
            btn_row, text="  确  认  ",
            bg=self.ACCENT, fg="white",
            font=("Microsoft YaHei", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=10, pady=6,
            command=self._submit
        ).pack(side="right", padx=(6, 0))
        tk.Button(
            btn_row, text="  取  消  ",
            bg="#F1F5F9", fg="#374151",
            font=self.FONT, relief="flat",
            cursor="hand2", padx=10, pady=6,
            command=self.destroy
        ).pack(side="right")

        self.bind("<Return>", lambda _: self._submit())
        self.bind("<Escape>", lambda _: self.destroy())

        # 居中对齐到父窗口
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")

    # ── 图片加载 ───────────────────────────────────────────
    def _load_image(self, img_bytes: bytes):
        """尝试用 Pillow 显示验证码图片，放大 2.5x 方便辨认。"""
        self._photo_ref = None
        if HAS_PIL and img_bytes:
            try:
                img = _PilImage.open(_io.BytesIO(img_bytes)).convert("RGBA")
                w, h = img.size
                scale = max(2, int(120 / h))
                img = img.resize((w * scale, h * scale), _PilImage.NEAREST)
                self._photo_ref = _PilImageTk.PhotoImage(img)
                self._img_label.configure(image=self._photo_ref, text="")
                return
            except Exception:
                pass

        # Pillow 不可用 / 加载失败 → 文字提示 + 浏览器按钮
        self._img_label.configure(
            text="[ 无法显示图片 ]",
            fg=self.GRAY, font=self.FONT_S
        )

    # ── 刷新验证码 ─────────────────────────────────────────
    def _refresh_captcha(self):
        self._img_label.configure(text="加载中…", image="", fg=self.GRAY)
        self._photo_ref = None

        def _fetch():
            try:
                r = self._session.get(
                    f"{PORTAL_BASE}/Self/login/randomCode?t={int(time.time()*1000)}",
                    timeout=8
                )
                self.after(0, lambda: self._load_image(r.content))
            except Exception as e:
                self.after(0, lambda: self._img_label.configure(
                    text=f"刷新失败: {e}", image=""
                ))

        threading.Thread(target=_fetch, daemon=True).start()

    # ── 确认提交 ───────────────────────────────────────────
    def _submit(self):
        code = self._code_var.get().strip()
        if not code:
            self._entry.configure(highlightthickness=2,
                                  highlightbackground=self.DANGER)
            self._entry.focus_set()
            return
        self.result = code
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  GUI 主窗口
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):

    # ── 调色板 ────────────────────────────────────────────
    ACCENT    = "#2563EB"
    ACCENT_LT = "#BFDBFE"
    ACCENT_DK = "#1D4ED8"
    BG        = "#F0F4F8"
    CARD      = "#FFFFFF"
    BORDER    = "#E2E8F0"
    GRAY      = "#9CA3AF"
    GRAY_DK   = "#6B7280"
    SUCCESS   = "#059669"
    WARN      = "#D97706"
    DANGER    = "#DC2626"
    TEXT      = "#1E293B"

    FONT   = ("Microsoft YaHei", 10)
    FONT_H = ("Microsoft YaHei", 11, "bold")
    FONT_S = ("Microsoft YaHei", 9)
    FONT_M = ("Microsoft YaHei", 8)
    FONT_T = ("Microsoft YaHei", 8)

    def __init__(self):
        super().__init__()
        self.title("AUST 校园认证助手 v1.2lite")
        self.geometry("920x720")
        self.minsize(820, 620)
        self.resizable(True, True)
        self.configure(bg=self.BG)

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
        main.pack(fill="both", expand=True, padx=18, pady=14)

        left = tk.Frame(main, bg=self.BG)
        left.pack(side="left", fill="y", expand=False, padx=(0, 14))

        right = tk.Frame(main, bg=self.BG)
        right.pack(side="right", fill="both", expand=True)

        self._build_left(left)
        self._build_right(right)

    def _build_header(self):
        h = tk.Frame(self, bg=self.ACCENT_DK, pady=12)
        h.pack(fill="x")
        inner = tk.Frame(h, bg=self.ACCENT_DK)
        inner.pack()
        tk.Label(inner, text="🏫  AUST 校园认证助手",
                 bg=self.ACCENT_DK, fg="white",
                 font=("Microsoft YaHei", 13, "bold")).pack(side="left")
        tk.Label(inner, text="   v1.2lite",
                 bg=self.ACCENT_DK, fg=self.ACCENT_LT,
                 font=("Microsoft YaHei", 9)).pack(side="left", pady=(2, 0))
        tk.Label(h, text="安徽理工大学  ·  校园网 & 教务系统一键认证",
                 bg=self.ACCENT_DK, fg=self.ACCENT_LT,
                 font=self.FONT_S).pack(pady=(2, 0))

    def _card(self, parent, title: str, subtitle: str = "") -> tk.LabelFrame:
        f = tk.LabelFrame(
            parent, text=f"  {title}  ", bg=self.CARD,
            font=("Microsoft YaHei", 9, "bold"),
            fg=self.TEXT, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.BORDER,
            padx=12, pady=10
        )
        return f

    # ══════════════════════════════════════════════════════
    #  左侧
    # ══════════════════════════════════════════════════════
    def _build_left(self, parent):
        self._build_account_card(parent)
        self._build_network_card(parent)
        self._build_jwgl_card(parent)
        self._build_auth_btn(parent)
        self._build_options_row(parent)

    def _build_account_card(self, parent):
        card = self._card(parent, "👤  账号信息")
        card.pack(fill="x", pady=(0, 8))
        for i, (label, attr, pwd) in enumerate([
            ("学号 / 工号", "_username", False),
            ("登录密  码", "_password", True),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=i, column=0, padx=(0, 8), pady=5)
            var = tk.StringVar()
            setattr(self, attr, var)
            e = tk.Entry(card, textvariable=var,
                         show="*" if pwd else "",
                         font=self.FONT, width=20,
                         relief="solid", bd=1)
            e.grid(row=i, column=1, pady=5, sticky="w")

    def _build_network_card(self, parent):
        card = self._card(parent, "🌐  校园网设置")
        card.pack(fill="x", pady=(0, 8))

        for row, (label, attr, values) in enumerate([
            ("运  营  商", "_isp_var",      list(ISP_MAP.keys())),
            ("网络类  型", "_net_type_var", NET_TYPE),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=row, column=0, padx=(0, 8), pady=5)
            var = tk.StringVar(value=values[0])
            setattr(self, attr, var)
            ttk.Combobox(card, textvariable=var, values=values,
                         state="readonly", width=15, font=self.FONT
                         ).grid(row=row, column=1, pady=5, sticky="w")

        tk.Label(card, text="账号预览", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=2, column=0, padx=(0, 8), pady=4)
        self._preview_var = tk.StringVar()
        tk.Label(card, textvariable=self._preview_var,
                 bg=self.CARD, fg=self.GRAY_DK,
                 font=("Consolas", 9)).grid(row=2, column=1, pady=4, sticky="w")

        self._username.trace_add("write", self._update_preview)
        self._isp_var.trace_add("write",  self._update_preview)
        self._update_preview()

    def _build_jwgl_card(self, parent):
        card = self._card(parent, "📚  教务系统")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(card, text="⚙️  功能开发中，敬请期待",
                 bg="#FEF9EE", fg="#92400E",
                 font=self.FONT_M, padx=8, pady=5
                 ).pack(fill="x", pady=(2, 0))

    def _build_auth_btn(self, parent):
        self._btn = tk.Button(
            parent, text="🚀  一键认证",
            bg=self.ACCENT, fg="white",
            font=("Microsoft YaHei", 11, "bold"),
            activebackground=self.ACCENT_DK,
            activeforeground="white",
            relief="flat", cursor="hand2",
            padx=12, pady=9,
            command=self._start
        )
        self._btn.pack(fill="x", pady=(4, 6))

    def _build_options_row(self, parent):
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x")

        self._save_var    = tk.BooleanVar(value=True)
        self._do_net_var  = tk.BooleanVar(value=True)
        self._startup_var = tk.BooleanVar(value=is_startup_enabled())

        options = [
            ("💾 保存配置",   self._save_var,    None),
            ("📡 认证校园网",  self._do_net_var,  None),
        ]
        if is_windows():
            options.append(("🔄 开机自启", self._startup_var, self._on_startup_toggle))

        for text, var, cmd in options:
            tk.Checkbutton(row, text=text, variable=var, bg=self.BG,
                           font=self.FONT_S, command=cmd,
                           activebackground=self.BG).pack(side="left", padx=(0, 4))

        if not is_windows():
            tk.Label(row, text="⚠ 自启仅 Win",
                     bg=self.BG, fg=self.GRAY, font=self.FONT_T).pack(side="left")

    # ══════════════════════════════════════════════════════
    #  右侧
    # ══════════════════════════════════════════════════════
    def _build_right(self, parent):
        top = tk.Frame(parent, bg=self.BG)
        top.pack(fill="x", pady=(0, 8))
        tk.Button(top, text="🎨 背景色",
                  bg="#E5E7EB", fg="#374151",
                  font=self.FONT_S, relief="flat",
                  cursor="hand2", padx=8,
                  command=self._choose_bg_color).pack(side="right")

        self._build_status_card(parent)
        self._build_portal_panel(parent)

    # ── 状态卡 ────────────────────────────────────────────
    def _build_status_card(self, parent):
        card = tk.Frame(parent, bg=self.CARD,
                        highlightthickness=1, highlightbackground=self.BORDER,
                        padx=12, pady=10)
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text="认证状态",
                 bg=self.CARD, fg=self.GRAY_DK,
                 font=("Microsoft YaHei", 8, "bold")).pack(anchor="w", pady=(0, 6))

        status_row = tk.Frame(card, bg=self.CARD)
        status_row.pack(fill="x", pady=(0, 4))
        self._net_status  = self._badge_label(status_row, "DrCOM 校园网")
        self._jwgl_status = self._badge_label(status_row, "教务系统")

        tk.Frame(card, bg=self.BORDER, height=1).pack(fill="x", pady=(4, 6))

        self._log = tk.Text(
            card, height=4, state="disabled",
            bg="#F8FAFC", relief="flat",
            font=("Consolas", 8), fg="#475569",
            wrap="word"
        )
        self._log.pack(fill="x")

    def _badge_label(self, parent, label: str) -> tk.StringVar:
        f = tk.Frame(parent, bg=self.CARD)
        f.pack(side="left", padx=(0, 12))
        tk.Label(f, text=label, bg=self.CARD,
                 fg=self.GRAY, font=self.FONT_T).pack(anchor="w")
        var = tk.StringVar(value="● 未认证")
        tk.Label(f, textvariable=var, bg=self.CARD,
                 font=("Microsoft YaHei", 8, "bold"),
                 fg=self.GRAY).pack(anchor="w")
        return var

    # ══════════════════════════════════════════════════════
    #  折叠自助系统面板
    # ══════════════════════════════════════════════════════
    def _build_portal_panel(self, parent):
        wrapper = tk.Frame(parent, bg=self.BG)
        wrapper.pack(fill="both", expand=True)

        self._portal_toggle_btn = tk.Button(
            wrapper,
            text="▼  📊 校园网自助系统",
            bg=self.ACCENT, fg="white",
            font=("Microsoft YaHei", 9, "bold"),
            relief="flat", cursor="hand2",
            anchor="w", padx=10, pady=7,
            activebackground=self.ACCENT_DK,
            activeforeground="white",
            command=self._toggle_portal
        )
        self._portal_toggle_btn.pack(fill="x")

        self._portal_outer = tk.Frame(wrapper, bg=self.BG)
        self._portal_outer.pack(fill="both", expand=True)

        tk.Frame(self._portal_outer, bg=self.ACCENT, width=3).pack(side="left", fill="y")

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

        # 控制行
        ctrl = tk.Frame(parent, bg=self.CARD)
        ctrl.pack(fill="x", pady=(0, 8))

        self._portal_status_var = tk.StringVar(value="● 未连接")
        self._portal_status_lbl = tk.Label(
            ctrl, textvariable=self._portal_status_var,
            bg=self.CARD, fg=self.GRAY,
            font=("Microsoft YaHei", 9, "bold")
        )
        self._portal_status_lbl.pack(side="left")

        btn_row = tk.Frame(ctrl, bg=self.CARD)
        btn_row.pack(side="right")

        self._portal_login_btn = tk.Button(
            btn_row, text="登 录",
            bg=self.ACCENT, fg="white",
            font=self.FONT_S, relief="flat",
            cursor="hand2", padx=10, pady=4,
            command=self._portal_do_login
        )
        self._portal_login_btn.pack(side="left", padx=(0, 4))

        self._portal_refresh_btn = tk.Button(
            btn_row, text="↻ 刷新",
            bg="#EFF6FF", fg=self.ACCENT,
            font=self.FONT_S, relief="flat",
            cursor="hand2", padx=6, pady=4,
            command=self._portal_do_refresh, state="disabled"
        )
        self._portal_refresh_btn.pack(side="left", padx=(0, 4))

        self._portal_logout_btn = tk.Button(
            btn_row, text="注 销",
            bg="#FEE2E2", fg=self.DANGER,
            font=self.FONT_S, relief="flat",
            cursor="hand2", padx=8, pady=4,
            command=self._portal_do_logout, state="disabled"
        )
        self._portal_logout_btn.pack(side="left")

        # 统计行
        tk.Frame(parent, bg=self.BORDER, height=1).pack(fill="x", pady=(0, 8))

        stats_f = tk.Frame(parent, bg=self.CARD)
        stats_f.pack(fill="x", pady=(0, 8))
        stats_f.columnconfigure((0, 1, 2), weight=1)

        self._stat_vars: dict = {}
        for col, (key, label, default, icon) in enumerate([
            ("flow",   "当期流量", "-- MB",  "📊"),
            ("time",   "已用时长", "-- min", "⏱"),
            ("expiry", "到期日期", "----",   "📅"),
        ]):
            cell = tk.Frame(stats_f, bg="#F8FAFC",
                            highlightthickness=1, highlightbackground=self.BORDER,
                            padx=4, pady=6)
            cell.grid(row=0, column=col, padx=2, sticky="nsew")
            tk.Label(cell, text=icon, bg="#F8FAFC", font=("", 11)).pack()
            var = tk.StringVar(value=default)
            self._stat_vars[key] = var
            tk.Label(cell, textvariable=var, bg="#F8FAFC",
                     font=("Microsoft YaHei", 8, "bold"),
                     fg=self.TEXT, wraplength=70).pack()
            tk.Label(cell, text=label, bg="#F8FAFC",
                     fg=self.GRAY, font=self.FONT_T).pack()

        # 设备列表
        tk.Frame(parent, bg=self.BORDER, height=1).pack(fill="x", pady=(2, 8))

        dev_hdr = tk.Frame(parent, bg=self.CARD)
        dev_hdr.pack(fill="x", pady=(0, 4))
        self._device_count_var = tk.StringVar(value="📱 在线设备")
        tk.Label(dev_hdr, textvariable=self._device_count_var,
                 bg=self.CARD, fg=self.TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        self._offline_all_btn = tk.Button(
            dev_hdr, text="全部下线",
            bg="#FEE2E2", fg=self.DANGER,
            font=self.FONT_M, relief="flat",
            cursor="hand2", padx=7, pady=2,
            command=self._portal_offline_all, state="disabled"
        )
        self._offline_all_btn.pack(side="right")

        list_outer = tk.Frame(parent, bg="#F1F5F9",
                              highlightthickness=1, highlightbackground=self.BORDER)
        list_outer.pack(fill="both", expand=True)

        self._dev_canvas = tk.Canvas(list_outer, bg="#F1F5F9", highlightthickness=0)
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
        tk.Label(self._dev_list_frame, text="暂无在线设备",
                 bg="#F1F5F9", fg=self.GRAY, font=self.FONT_S).pack(pady=20)

    # ══════════════════════════════════════════════════════
    #  验证码获取（供 portal_login 回调）
    # ══════════════════════════════════════════════════════
    def _get_captcha_from_user(self, session, img_bytes: bytes) -> str | None:
        """
        从后台线程调用，切换到主线程显示弹窗，阻塞等待用户输入后返回。
        返回 None 表示用户取消或超时。
        """
        result   = [None]
        done_evt = threading.Event()

        def _show():
            dlg = CaptchaDialog(self, session, img_bytes)
            self.wait_window(dlg)
            result[0] = dlg.result
            done_evt.set()

        self.after(0, _show)
        done_evt.wait(timeout=120)   # 最多等 2 分钟
        return result[0]

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
        self._portal_status_var.set("⏳ 等待验证码…")
        self._portal_status_lbl.config(fg=self.WARN)
        threading.Thread(target=self._portal_login_thread,
                         args=(u, p), daemon=True).start()

    def _portal_login_thread(self, u, p):
        r = portal_login(u, p, self._get_captcha_from_user)

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
            else:
                self._portal_status_var.set("● 未连接")
                self._portal_status_lbl.config(fg=self.DANGER)
                if r["error"] != "用户取消":
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
                flow_mb = stats.get("used_flow_mb")
                if flow_mb is not None:
                    self._stat_vars["flow"].set(
                        f"{flow_mb/1024:.2f} GB" if flow_mb >= 1024 else f"{int(flow_mb)} MB"
                    )
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
            self._devices = dev_r.get("devices", []) if dev_r["success"] else []
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
        if not messagebox.askyesno("确认", f"确定下线全部 {len(self._devices)} 台设备？"):
            return
        self._offline_all_btn.config(state="disabled")
        threading.Thread(target=self._offline_all_thread, daemon=True).start()

    def _offline_all_thread(self):
        ok, total = 0, len(self._devices)
        for d in list(self._devices):
            r = portal_offline_device(
                self._portal_session,
                d.get("sessionId"), d.get("ip"), d.get("mac")
            )
            if r["success"]:
                ok += 1
            time.sleep(0.8)
        self.after(0, lambda: self._log_msg(f"📴 已下线 {ok}/{total} 台设备"))
        self.after(0, self._portal_do_refresh)

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
        # 去重（以 IP 为键）
        seen, uniq = set(), []
        for d in self._devices:
            ip = d.get("ip")
            if ip and ip not in seen:
                seen.add(ip); uniq.append(d)
            elif not ip:
                uniq.append(d)
        self._devices = uniq

        for w in self._dev_list_frame.winfo_children():
            w.destroy()

        if not self._devices:
            tk.Label(self._dev_list_frame, text="暂无在线设备",
                     bg="#F1F5F9", fg=self.GRAY, font=self.FONT_S).pack(pady=20)
            self._device_count_var.set("📱 在线设备（0 台）")
            self._offline_all_btn.config(state="disabled")
            return

        n = len(self._devices)
        self._device_count_var.set(f"📱 在线设备（{n} 台）")
        self._offline_all_btn.config(state="normal")

        for idx, device in enumerate(self._devices):
            self._build_device_row(idx, device)
            if idx < n - 1:
                tk.Frame(self._dev_list_frame, bg=self.BORDER, height=1).pack(fill="x")

        self._dev_list_frame.update_idletasks()
        self._dev_canvas.configure(
            scrollregion=self._dev_canvas.bbox("all"),
            width=self._portal_body.winfo_width() - 36
        )

    def _build_device_row(self, idx: int, device: dict):
        mac    = device.get("mac", "")
        ip     = device.get("ip", "N/A")
        row_bg = self.CARD if idx % 2 == 0 else "#F8FAFC"

        row = tk.Frame(self._dev_list_frame, bg=row_bg, pady=6, padx=8)
        row.pack(fill="x")

        line1 = tk.Frame(row, bg=row_bg)
        line1.pack(fill="x")

        badge_text, badge_bg = self._terminal_badge(device.get("terminalType", ""))
        tk.Label(line1, text=badge_text, bg=badge_bg, fg="white",
                 font=self.FONT_T, padx=4, pady=1).pack(side="left", padx=(0, 6))
        tk.Label(line1, text=ip, bg=row_bg,
                 font=("Consolas", 9, "bold"), fg=self.TEXT).pack(side="left")
        flow_mb = float(device.get("downFlow", 0)) / 1024
        tk.Label(line1, text=f"  ↓{flow_mb:.1f} MB",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_T).pack(side="left")

        offline_btn = tk.Button(
            line1, text="下 线",
            bg="#FEE2E2", fg=self.DANGER,
            font=self.FONT_T, relief="flat",
            cursor="hand2", padx=5, pady=1
        )
        offline_btn.config(command=lambda d=device, b=offline_btn: self._portal_offline_one(d, b))
        offline_btn.pack(side="right")

        line2 = tk.Frame(row, bg=row_bg)
        line2.pack(fill="x", pady=(3, 0))

        use_time = device.get("useTime", "--")
        tk.Label(line2, text=f"⏱ {use_time} min",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_T).pack(side="left")
        tk.Label(line2, text="  标签:",
                 bg=row_bg, fg=self.GRAY, font=self.FONT_T).pack(side="left")

        label_var = tk.StringVar(value=self._device_labels.get(mac, ""))
        combo = ttk.Combobox(line2, textvariable=label_var,
                             values=PRESET_LABELS, width=13, font=self.FONT_T)
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

    _SKIP_BG = frozenset({
        "#FFFFFF", "#2563EB", "#1D4ED8", "#DBEAFE", "#FEF3C7", "#FEF9EE",
        "#F8FAFC", "#F1F5F9", "#F3F4F6", "#FEE2E2", "#F9FAFB", "#EFF6FF",
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

    # ── DrCOM 认证 ────────────────────────────────────────
    def _start(self):
        username = self._username.get().strip()
        password = self._password.get().strip()
        isp_key  = self._isp_var.get()
        net_type = self._net_type_var.get()

        if not username or not password:
            messagebox.showwarning("提示", "请填写账号和密码")
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
        self._jwgl_status.set("⚙️  待完善")

        isp_suffix = ISP_MAP.get(isp_key, "aust")
        threading.Thread(
            target=self._run_auth,
            args=(username, password, isp_suffix, net_type),
            daemon=True
        ).start()

    def _run_auth(self, username, password, isp_suffix, net_type):
        if self._do_net_var.get():
            self._log_msg(f"→ 校园网  {username}@{isp_suffix}  [{net_type}]")
            r = login_drcom(username, password, isp_suffix, net_type)
            if r["success"]:
                note = r.get("note", "")
                self.after(0, lambda: self._net_status.set(f"✅ 成功 {note}".strip()))
                self._log_msg(f"✅ 校园网认证成功 {note}".strip())
            else:
                self.after(0, lambda: self._net_status.set("❌ 失败"))
                self._log_msg(f"❌ 校园网：{r['error']}")
        else:
            self.after(0, lambda: self._net_status.set("⬛ 已跳过"))
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