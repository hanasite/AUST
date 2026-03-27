"""
安徽理工大学 - 校园网自动认证工具 (AUST-ConnectEase)
版本 v1.1
- 界面左右分栏，更紧凑
- 右侧顶部添加自定义背景功能
- 状态日志移至右侧，减小窗口高度
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import threading
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".school_auth_config.json")

# ─────────────────────────────────────────────
#  开机自启动（Windows 注册表）
# ─────────────────────────────────────────────

APP_NAME = "AUST_ConnectEase"
RUN_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_startup_cmd() -> str:
    """返回写入注册表的启动命令。打包为 exe 时直接用 exe 路径，否则用 pythonw + 脚本路径。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        script  = os.path.abspath(__file__)
        return f'"{pythonw}" "{script}"'


def is_startup_enabled() -> bool:
    """检查注册表中是否已存在自启动项。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup(enable: bool) -> bool:
    """
    enable=True  → 写入注册表，添加自启动
    enable=False → 删除注册表项，取消自启动
    返回 True 表示操作成功。
    """
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY,
            0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_startup_cmd())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
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


# ─────────────────────────────────────────────
#  校园网认证逻辑
# ─────────────────────────────────────────────

DRCOM_URL = "http://10.255.0.19/drcom/login"

ISP_MAP = {
    "电信  (@aust)":   "aust",
    "联通  (@unicom)": "unicom",
    "移动  (@cmcc)":   "cmcc",
    "教职工 (@jzg)":   "jzg",
}

NET_TYPE = ["宽带（POST）", "WiFi（GET）"]


def parse_drcom_response(text: str) -> dict:
    json_match = re.search(r'\((\{.*\})\)', text, re.DOTALL)
    if not json_match:
        return {"success": False, "error": f"无法解析响应: {text[:100]}"}

    try:
        data = json.loads(json_match.group(1))
    except json.JSONDecodeError:
        return {"success": False, "error": f"JSON解析失败: {text[:100]}"}

    result = data.get("result", -1)

    if result == 1:
        ip   = data.get("v46ip", "")
        note = f"（IP: {ip}）" if ip else ""
        return {"success": True, "note": note, "data": data}

    if result == 0:
        msg = data.get("msg", "") or data.get("info", "") or data.get("err", "")
        if not msg:
            ecode     = data.get("ecode", "")
            error_map = {
                "E2553": "密码错误，请检查后重试",
                "E2901": "该账号已在线",
                "E2905": "账户欠费，请充值",
            }
            msg = error_map.get(str(ecode), f"认证失败 (code={ecode})")
        if "已在线" in msg or "online" in msg.lower():
            return {"success": True, "note": "（该账号已在线）"}
        return {"success": False, "error": msg}

    return {"success": False, "error": f"未知结果码 result={result}"}


def login_drcom(username: str, password: str, isp_suffix: str, net_type: str) -> dict:
    account = f"{username}@{isp_suffix}"
    params  = {
        "callback": "dr1003",
        "DDDDD":    account,
        "upass":    password,
        "0MKKey":   "123456",
    }
    try:
        session = requests.Session()
        if net_type == "宽带（POST）":
            resp = session.post(DRCOM_URL, data=params, timeout=10)
        else:
            resp = session.get(DRCOM_URL, params=params, timeout=10)
        return parse_drcom_response(resp.text)
    except requests.exceptions.ConnectionError:
        return {"success": False,
                "error": "无法连接认证服务器 (10.255.0.19)\n请确认已接入校园网 WiFi / 有线"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "认证服务器超时，请重试"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
#  配置读写
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
#  GUI 主窗口（左右分栏布局）
# ─────────────────────────────────────────────

class App(tk.Tk):
    ACCENT = "#2563EB"
    BG     = "#F0F4F8"
    CARD   = "#FFFFFF"
    GRAY   = "#9CA3AF"
    FONT   = ("Microsoft YaHei", 10)
    FONT_H = ("Microsoft YaHei", 11, "bold")
    FONT_S = ("Microsoft YaHei", 9)

    def __init__(self):
        super().__init__()
        self.title("AUST 校园认证助手 v1.1")
        self.resizable(False, False)
        self.configure(bg=self.BG)
        self._build_ui()
        self._load_saved()

    # ── 界面构建 ────────────────────────────────

    def _build_ui(self):
        self._build_header()

        # 主内容区：左右分栏
        main = tk.Frame(self, bg=self.BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)

        # 左侧区域（核心操作）
        left = tk.Frame(main, bg=self.BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 右侧区域（辅助功能 + 状态）
        right = tk.Frame(main, bg=self.BG)
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # --- 左侧内容 ---
        self._build_account_card(left, row=0)
        self._build_network_card(left, row=1)
        self._build_jwgl_placeholder(left, row=2)
        self._build_button(left, row=3)  # 认证按钮放左侧底部

        # --- 右侧内容 ---
        self._build_right_top(right)      # 自定义背景 + 复选框
        self._build_right_status(right)   # 状态监控 + 日志

    def _build_header(self):
        h = tk.Frame(self, bg=self.ACCENT, pady=14)
        h.pack(fill="x")
        tk.Label(h, text="🏫  AUST 校园认证助手",
                 bg=self.ACCENT, fg="white",
                 font=("Microsoft YaHei", 14, "bold")).pack()
        tk.Label(h, text="安徽理工大学  •  教务系统 & 校园网一键认证",
                 bg=self.ACCENT, fg="#BFDBFE", font=self.FONT_S).pack(pady=(2, 0))

    def _lf(self, parent, title):
        """创建一个统一的 LabelFrame 卡片"""
        f = tk.LabelFrame(parent, text=title, bg=self.CARD, font=self.FONT_H,
                          fg="#1E3A5F", relief="flat", bd=1,
                          highlightthickness=1, highlightbackground="#D1D5DB",
                          padx=14, pady=10)
        return f

    # ---------- 左侧组件 ----------
    def _build_account_card(self, parent, row):
        card = self._lf(parent, "👤  账号信息")
        card.pack(fill="x", pady=(0, 10))

        for i, (label, attr, is_pwd) in enumerate([
            ("学号 / 工号", "_username", False),
            ("密       码", "_password", True),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=i, column=0, padx=12, pady=6)
            var = tk.StringVar()
            setattr(self, attr, var)
            tk.Entry(card, textvariable=var, show="*" if is_pwd else "",
                     font=self.FONT, width=26, relief="solid", bd=1
                     ).grid(row=i, column=1, padx=12, pady=6, sticky="w")

    def _build_network_card(self, parent, row):
        card = self._lf(parent, "🌐  校园网设置")
        card.pack(fill="x", pady=(0, 10))

        tk.Label(card, text="运营商", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=0, column=0, padx=12, pady=6)
        self._isp_var = tk.StringVar(value=list(ISP_MAP.keys())[0])
        ttk.Combobox(card, textvariable=self._isp_var,
                     values=list(ISP_MAP.keys()), state="readonly",
                     width=20, font=self.FONT
                     ).grid(row=0, column=1, padx=12, pady=6, sticky="w")

        tk.Label(card, text="网络类型", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=1, column=0, padx=12, pady=6)
        self._net_type_var = tk.StringVar(value=NET_TYPE[0])
        ttk.Combobox(card, textvariable=self._net_type_var,
                     values=NET_TYPE, state="readonly",
                     width=20, font=self.FONT
                     ).grid(row=1, column=1, padx=12, pady=6, sticky="w")

        tk.Label(card, text="账号预览", bg=self.CARD, font=self.FONT,
                 width=9, anchor="e").grid(row=2, column=0, padx=12, pady=4)
        self._preview_var = tk.StringVar()
        tk.Label(card, textvariable=self._preview_var, bg=self.CARD,
                 fg=self.GRAY, font=("Consolas", 9)
                 ).grid(row=2, column=1, padx=12, pady=4, sticky="w")

        self._username.trace_add("write", self._update_preview)
        self._isp_var.trace_add("write",  self._update_preview)
        self._update_preview()

    def _build_jwgl_placeholder(self, parent, row):
        card = self._lf(parent, "📚  教务系统登录")
        card.pack(fill="x", pady=(0, 10))

        for i, (label, placeholder) in enumerate([
            ("学号 / 工号", "与校园网账号相同"),
            ("密       码", "待完善功能"),
        ]):
            tk.Label(card, text=label, bg=self.CARD, font=self.FONT,
                     width=9, anchor="e").grid(row=i, column=0, padx=12, pady=6)
            entry = tk.Entry(card, font=self.FONT, width=26, relief="solid", bd=1,
                             bg="#F3F4F6", fg=self.GRAY, state="disabled",
                             disabledforeground=self.GRAY, disabledbackground="#F3F4F6")
            entry.grid(row=i, column=1, padx=12, pady=6, sticky="w")
            entry.config(state="normal")
            entry.insert(0, placeholder)
            entry.config(state="disabled")

        badge = tk.Label(card, text="⚙️  功能开发中，敬请期待",
                         bg="#FEF3C7", fg="#92400E",
                         font=("Microsoft YaHei", 8),
                         relief="flat", padx=8, pady=3)
        badge.grid(row=2, column=0, columnspan=2, padx=12, pady=(4, 2), sticky="w")

    def _build_button(self, parent, row):
        self._btn = tk.Button(parent, text="🚀  一键认证",
                              bg=self.ACCENT, fg="white",
                              font=("Microsoft YaHei", 11, "bold"),
                              relief="flat", cursor="hand2",
                              padx=12, pady=9, command=self._start)
        self._btn.pack(fill="x", pady=(5, 0))

    # ---------- 右侧组件 ----------
    def _build_right_top(self, parent):
        """右侧顶部：自定义背景按钮 + 功能复选框"""
        top_frame = tk.Frame(parent, bg=self.BG)
        top_frame.pack(fill="x", pady=(0, 10))

        # 自定义背景按钮
        self._bg_btn = tk.Button(top_frame, text="🎨 自定义背景",
                                 bg="#E5E7EB", fg="#1F2937",
                                 font=self.FONT, relief="flat",
                                 cursor="hand2", command=self._choose_bg_color)
        self._bg_btn.pack(side="left", padx=(0, 10))

        # 复选框区域（垂直排列）
        cb_frame = tk.Frame(top_frame, bg=self.BG)
        cb_frame.pack(side="left", fill="x", expand=True)

        self._save_var    = tk.BooleanVar(value=True)
        self._do_net_var  = tk.BooleanVar(value=True)
        self._startup_var = tk.BooleanVar(value=is_startup_enabled())

        for text, var, cmd in [
            ("💾  保存配置（下次自动填入）", self._save_var,    None),
            ("📡  认证校园网",              self._do_net_var,   None),
            ("🔄  开机自启动",              self._startup_var,  self._on_startup_toggle),
        ]:
            cb = tk.Checkbutton(cb_frame, text=text, variable=var,
                                bg=self.BG, font=self.FONT,
                                command=cmd)
            cb.pack(anchor="w")

        if not is_windows():
            self._startup_var.set(False)
            for child in cb_frame.winfo_children():
                if isinstance(child, tk.Checkbutton) and "自启动" in str(child.cget("text")):
                    child.config(state="disabled", fg=self.GRAY)
            tk.Label(cb_frame, text="  ⚠ 自启动仅支持 Windows",
                     bg=self.BG, fg=self.GRAY, font=("Microsoft YaHei", 8)
                     ).pack(anchor="w", padx=4)

    def _build_right_status(self, parent):
        """右侧底部：状态监控 + 日志"""
        card = tk.Frame(parent, bg=self.CARD, relief="flat", bd=1,
                        highlightthickness=1, highlightbackground="#D1D5DB",
                        padx=14, pady=10)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="认证状态", bg=self.CARD, fg=self.GRAY,
                 font=("Microsoft YaHei", 9, "bold")).pack(anchor="w", pady=(0, 4))

        self._net_status  = self._status_row(card, "校园网")
        self._jwgl_status = self._status_row(card, "教务系统")

        tk.Frame(card, bg="#E5E7EB", height=1).pack(fill="x", pady=6)

        self._log = tk.Text(card, height=6, width=40, state="disabled",
                            bg="#F9FAFB", relief="flat", font=("Consolas", 9),
                            fg="#374151", wrap="word")
        self._log.pack(fill="both", expand=True)

    def _status_row(self, parent, label):
        f = tk.Frame(parent, bg=self.CARD)
        f.pack(anchor="w", pady=1)
        tk.Label(f, text=f"{label}：", bg=self.CARD, font=self.FONT_S,
                 width=9, anchor="w").pack(side="left")
        var = tk.StringVar(value="⬜ 未认证")
        tk.Label(f, textvariable=var, bg=self.CARD, font=self.FONT_S).pack(side="left")
        return var

    # ── 辅助方法 ──
    def _update_preview(self, *_):
        uid    = self._username.get().strip() or "学号"
        suffix = ISP_MAP.get(self._isp_var.get(), "aust")
        self._preview_var.set(f"{uid}@{suffix}")

    def _choose_bg_color(self):
        """弹出颜色选择器，更改窗口背景色"""
        color_code = colorchooser.askcolor(title="选择背景颜色", initialcolor=self.BG)[1]
        if color_code:
            self.BG = color_code
            self.configure(bg=self.BG)
            # 更新所有主要 Frame 的背景（递归处理）
            for widget in [self, self._bg_btn.master.master.master, self._log.master.master]:  # 简化：只更新几个顶层容器
                try:
                    widget.configure(bg=self.BG)
                except:
                    pass
            self._log_msg(f"🎨 背景色已更改为 {color_code}")

    def _on_startup_toggle(self):
        enable = self._startup_var.get()
        ok = set_startup(enable)
        if ok:
            state = "已开启" if enable else "已关闭"
            self._log_msg(f"🔄 开机自启动{state}")
        else:
            self._startup_var.set(not enable)

    # ── 配置加载 ──
    def _load_saved(self):
        cfg = load_config()
        if cfg.get("username"): self._username.set(cfg["username"])
        if cfg.get("password"): self._password.set(cfg["password"])
        if cfg.get("isp") and cfg["isp"] in ISP_MAP:
            self._isp_var.set(cfg["isp"])
        if cfg.get("net_type") and cfg["net_type"] in NET_TYPE:
            self._net_type_var.set(cfg["net_type"])
        if cfg.get("do_net") is not None:
            self._do_net_var.set(cfg["do_net"])

    # ── 认证主流程 ──
    def _start(self):
        username = self._username.get().strip()
        password = self._password.get().strip()
        isp_key  = self._isp_var.get()
        net_type = self._net_type_var.get()

        if not username or not password:
            messagebox.showwarning("提示", "请填写学号和密码")
            return

        if self._save_var.get():
            save_config({
                "username": username,
                "password": password,
                "isp":      isp_key,
                "net_type": net_type,
                "do_net":   self._do_net_var.get(),
            })
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