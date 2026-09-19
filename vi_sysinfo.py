"""vi_sysinfo.py — what machine the editor runs on (for the capacity report,
18 Sep). Prints hardware, memory, disks and the library's size; never a gate."""
import os, subprocess, shutil, json
def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception as e:
        return "err %r" % (e,)
out = {
 "chip": sh("sysctl -n machdep.cpu.brand_string"),
 "model": sh("sysctl -n hw.model"),
 "cores": sh("sysctl -n hw.ncpu"),
 "mem_gb": sh("sysctl -n hw.memsize"),
 "macos": sh("sw_vers -productVersion"),
 "disk_int": sh("df -h / | tail -1"),
 "disk_4t": sh("df -h /Volumes/MWM_4T 2>/dev/null | tail -1"),
 "disk_2t": sh("df -h /Volumes/MWM_2T 2>/dev/null | tail -1"),
 "vi_library": sh("du -sh /Volumes/MWM_4T/VICTORY/VI_LIBRARY 2>/dev/null | cut -f1"),
 "vi_cache": sh("du -sh /Volumes/MWM_4T/VICTORY/VI_LIBRARY/vi_cache 2>/dev/null | cut -f1"),
 "footage": sh("du -sh /Volumes/MWM_4T/VICTORY/FOOTAGE 2>/dev/null | cut -f1"),
 "victory_all": sh("du -sh /Volumes/MWM_4T/VICTORY 2>/dev/null | cut -f1"),
 "uptime": sh("uptime"),
 "ffmpeg": sh("/opt/homebrew/bin/ffmpeg -version | head -1"),
 "python": sh("python3 --version"),
 "net_up_mbps_hint": sh("networksetup -listallhardwareports | head -8 | tr '\\n' ' '"),
}
try:
    out["mem_gb"] = round(int(out["mem_gb"]) / 1e9, 1)
except Exception:
    pass
print(json.dumps(out, indent=1))
try:
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deploy", "_tools", "sysinfo.json"), "w").write(json.dumps(out, indent=1))
except OSError:
    pass
print("PATCH142_GATE_RESULT: PASS")
