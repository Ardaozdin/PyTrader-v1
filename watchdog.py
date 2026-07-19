#!/usr/bin/env python3
"""
watchdog.py — Harici canlılık bekçisi (madde 37)

bot_worker.py her döngüde bot_heartbeat.txt'yi günceller. Bu script heartbeat
dosyasının tazeliğini kontrol eder; STALE_LIMIT_SEC'ten eskiyse bot "donmuş ama
canlı" demektir → süreci öldürüp yeniden başlatır. (NSSM çöken süreci yakalar;
watchdog DONMUŞ süreci yakalar.)

Windows Görev Zamanlayıcı ile 5 dakikada bir çalıştır, VEYA sürekli mod:
    python watchdog.py --loop
"""

import argparse
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT = os.path.join(BASE, "bot_heartbeat.txt")
BOT = os.path.join(BASE, "bot_worker.py")
STALE_LIMIT_SEC = 300  # 5 dk taze değilse donmuş say
CHECK_EVERY_SEC = 120


def _heartbeat_yasi():
    try:
        with open(HEARTBEAT, encoding="utf-8") as f:
            return time.time() - float(f.read().strip())
    except Exception:
        return None


def _bot_calisiyor_mu():
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*bot_worker.py*' }).Count"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out not in ("", "0")
    except Exception:
        return False


def _botu_oldur():
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*bot_worker.py*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _botu_baslat():
    try:
        subprocess.Popen([sys.executable, BOT], cwd=BASE,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    except Exception as e:
        print(f"watchdog: bot başlatılamadı: {e}", flush=True)


def kontrol():
    yas = _heartbeat_yasi()
    calisiyor = _bot_calisiyor_mu()
    if yas is None or not calisiyor:
        print(f"watchdog: bot yok/heartbeat yok (yaş={yas}, çalışıyor={calisiyor}) → başlatılıyor")
        _botu_baslat()
        return
    if yas > STALE_LIMIT_SEC:
        print(f"watchdog: DONMUŞ (heartbeat {yas:.0f}sn) → öldür+başlat")
        _botu_oldur()
        time.sleep(3)
        _botu_baslat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="Sürekli çalış")
    args = ap.parse_args()
    if args.loop:
        while True:
            kontrol()
            time.sleep(CHECK_EVERY_SEC)
    else:
        kontrol()


if __name__ == "__main__":
    main()
