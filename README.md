# VortexL2

**Stealth L2TPv3 Tunnel Manager** - تانل رمزنگاری شده و غیرقابل شناسایی

```
 __      __        _            _     ___  
 \ \    / /       | |          | |   |__ \ 
  \ \  / /__  _ __| |_ _____  _| |      ) |
   \ \/ / _ \| '__| __/ _ \ \/ / |     / / 
    \  / (_) | |  | ||  __/>  <| |____/ /_ 
     \/ \___/|_|   \__\___/_/\_\______|____|
                                     v3.0.0
```

## ⚡ Quick Install

**یک دستور برای همه سرورها:**

```bash
bash <(curl -Ls https://raw.githubusercontent.com/emad1381/VortexL2/main/stealth_install.sh)
```

بعد از اجرا، توی منو انتخاب کن:
- **[1] Kharej** - سرور خارج
- **[2] Iran** - سرور ایران

---

## ✨ Features

- 🛡️ **WireGuard Encryption** - رمزنگاری قوی و سریع
- 🌐 **wstunnel Obfuscation** - ترافیک شبیه HTTPS (پورت 443)
- 🚀 **HAProxy Port Forwarding** - پورت فوروارد حرفه‌ای
- 🔄 **Auto-Reconnect** - اتصال مجدد خودکار
- 📦 **One-Line Install** - نصب با یک دستور

---

## 🔧 Architecture

```
User → HAProxy → L2TPv3 → WireGuard → wstunnel → Internet (443)
       (forward)  (L2)    (encrypt)   (stealth)
```

---

## 📋 After Installation

```bash
# مدیریت تانل
sudo vortexl2

# وضعیت سرویس‌ها
systemctl status vortexl2-wstunnel
systemctl status vortexl2-tunnel

# لاگ‌ها
journalctl -u vortexl2-wstunnel -f
```

---

## 🔑 Key Exchange

بعد از نصب روی هر دو سرور:
1. Public Key سرور خارج رو کپی کن
2. توی سرور ایران `sudo vortexl2` بزن و کلید رو وارد کن
3. همین کار رو برعکس انجام بده

---

## ⚙️ Technical Specs

| Setting | Value |
|---------|-------|
| WireGuard MTU | 1280 |
| KeepAlive | 25s |
| wstunnel Port | 443 (wss://) |
| Encryption | WireGuard (ChaCha20) |

---

## 📞 Contact

- **GitHub:** [emad1381](https://github.com/emad1381)
- **Telegram:** [@emad1381](https://t.me/emad1381)

---

**License:** MIT