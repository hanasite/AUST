"""
安徽理工大学 - 校园网自动认证工具 (AUST-ConnectEase)
依赖: pip install requests
运行: python school_auth_v1.0.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import json
import os
import re

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".school_auth_config.json")

# ─────────────────────────────────────────────
#  校园网认证逻辑（AUST-ConnectEase）
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
    """
    解析 Dr.COM 返回的 JSONP 响应
    格式: dr1003({...})
    result=1 -> 成功, result=0 -> 失败
    """
    # 提取 JSONP 中的 JSON 部分
    json_match = re.search(r'\((\{.*\})\)', text, re.DOTALL)
    if not json_match:
        return {"success": False, "error": f"无法解析响应: {text[:100]}"}

    try:
        data = json.loads(json_match.group(1))
    except json.JSONDecodeError:
        return {"success": False, "error": f"JSON解析失败: {text[:100]}"}

    result = data.get("result", -1)

    if result == 1:
        # 登录成功，附带一些信息
        ip = data.get("v46ip", "")
        note = f"（IP: {ip}）" if ip else ""
        return {"success": True, "note": note, "data": data}

    if result == 0:
        # 登录失败，尝试提取错误信息
        msg = data.get("msg", "") or data.get("info", "") or data.get("err", "")
        if not msg:
            # 根据常见错误码判断
            ecode = data.get("ecode", "")
            error_map = {
                "E2553": "密码错误，请检查后重试",
                "E2901": "该账号已在线",
                "E2905": "账户欠费，请充值",
            }
            msg = error_map.get(str(ecode), f"认证失败 (code={ecode})")
        # 特判"已在线"
        if "已在线" in msg or "online" in msg.lower():
            return {"success": True, "note": "（该账号已在线）"}
        return {"success": False, "error": msg}

    return {"success": False, "error": f"未知结果码 result={result}"}


def login_drcom(username: str, password: str, isp_suffix: str, net_type: str) -> dict:
    """校园网 Dr.COM 认证"""
    account = f"{username}@{isp_suffix}"
    params = {
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
#  GUI 主窗口
# ─────────────────────────────────────────────

class App(tk.Tk):
    ACCENT  = "#2563EB"
    BG      = "#F0F4F8"
    CARD    = "#FFFFFF"
    GRAY    = "#9CA3AF"
    FONT    = ("Microsoft YaHei", 10)
    FONT_H  = ("Microsoft YaHei", 11, "bold")
    FONT_S  = ("Microsoft YaHei", 9)

    def __init__(self):
        super().__init__()
        self.title("AUST 校园认证助手")
        self.resizable(False, False)
        self.configure(bg=self.BG)
        self._build_ui()
        self._load_saved()

    # ── 界面构建 ────────────────────────────────

    def _build_ui(self):
        self._build_header()
        outer = tk.Frame(self, bg=self.BG, padx=20, pady=16)
        outer.pack()
        self._build_account_card(outer, row=0)
        self._build_network_card(outer, row=1)
        self._build_jwgl_placeholder(outer, row=2)
        self._build_options(outer, row=3)
        self._build_button(outer, row=4)
        self._build_status(outer, row=5)

    def _build_header(self):
        h = tk.Frame(self, bg=self.ACCENT, pady=14)
        h.pack(fill="x")
        tk.Label(h, text="🏫  AUST 校园认证助手",
                 bg=self.ACCENT, fg="white",
                 font=("Microsoft YaHei", 14, "bold")).pack()
        tk.Label(h, text="安徽理工大学  •  教务系统 & 校园网一键认证",
                 bg=self.ACCENT, fg="#BFDBFE", font=self.FONT_S).pack(pady=(2, 0))

    def _lf(self, parent, title, row):
        f = tk.LabelFrame(parent, text=title, bg=self.CARD, font=self.FONT_H,
                          fg="#1E3A5F", relief="flat", bd=1,
                          highlightthickness=1, highlightbackground="#D1D5DB",
                          padx=14, pady=10)
        f.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        return f

    def _build_account_card(self, parent, row):
        card = self._lf(parent, "👤  账号信息", row)
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
        card = self._lf(parent, "🌐  校园网设置", row)

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

    def _update_preview(self, *_):
        uid    = self._username.get().strip() or "学号"
        suffix = ISP_MAP.get(self._isp_var.get(), "aust")
        self._preview_var.set(f"{uid}@{suffix}")

    def _build_jwgl_placeholder(self, parent, row):
        """教务系统登录 - 待完善占位卡片"""
        card = self._lf(parent, "📚  教务系统登录", row)

        # 虚化的输入框（仅展示，不可交互）
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
            # 插入占位文字
            entry.config(state="normal")
            entry.insert(0, placeholder)
            entry.config(state="disabled")

        # 待完善标签
        badge = tk.Label(card, text="⚙️  功能开发中，敬请期待",
                         bg="#FEF3C7", fg="#92400E",
                         font=("Microsoft YaHei", 8),
                         relief="flat", padx=8, pady=3)
        badge.grid(row=2, column=0, columnspan=2, padx=12, pady=(4, 2), sticky="w")

    def _build_options(self, parent, row):
        f = tk.Frame(parent, bg=self.BG)
        f.grid(row=row, column=0, sticky="w", pady=2)
        self._save_var   = tk.BooleanVar(value=True)
        self._do_net_var = tk.BooleanVar(value=True)
        for text, var in [
            ("💾  保存配置（下次自动填入）", self._save_var),
            ("📡  认证校园网",              self._do_net_var),
        ]:
            tk.Checkbutton(f, text=text, variable=var,
                           bg=self.BG, font=self.FONT).pack(anchor="w")

    def _build_button(self, parent, row):
        self._btn = tk.Button(parent, text="🚀  一键认证",
                              bg=self.ACCENT, fg="white",
                              font=("Microsoft YaHei", 11, "bold"),
                              relief="flat", cursor="hand2",
                              padx=12, pady=9, command=self._start)
        self._btn.grid(row=row, column=0, pady=(8, 6), sticky="ew")

    def _build_status(self, parent, row):
        card = tk.Frame(parent, bg=self.CARD, relief="flat", bd=1,
                        highlightthickness=1, highlightbackground="#D1D5DB",
                        padx=14, pady=10)
        card.grid(row=row, column=0, sticky="ew")
        tk.Label(card, text="认证状态", bg=self.CARD, fg=self.GRAY,
                 font=("Microsoft YaHei", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._net_status  = self._status_row(card, "校园网")
        self._jwgl_status = self._status_row(card, "教务系统")
        tk.Frame(card, bg="#E5E7EB", height=1).pack(fill="x", pady=6)
        self._log = tk.Text(card, height=5, width=48, state="disabled",
                            bg="#F9FAFB", relief="flat", font=("Consolas", 9),
                            fg="#374151", wrap="word")
        self._log.pack(fill="x")

    def _status_row(self, parent, label):
        f = tk.Frame(parent, bg=self.CARD)
        f.pack(anchor="w", pady=1)
        tk.Label(f, text=f"{label}：", bg=self.CARD, font=self.FONT_S,
                 width=9, anchor="w").pack(side="left")
        var = tk.StringVar(value="⬜ 未认证")
        tk.Label(f, textvariable=var, bg=self.CARD, font=self.FONT_S).pack(side="left")
        return var

    # ── 配置加载 ──

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