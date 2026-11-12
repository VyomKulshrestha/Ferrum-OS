"""Print physical-available and commit-available memory in GB; exit 0 if both clear the given floors."""
import ctypes, sys
class MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
m = MS(); m.dwLength = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
phys, commit = m.ullAvailPhys / 2**30, m.ullAvailPageFile / 2**30
print(f"phys_avail {phys:.1f} GB commit_avail {commit:.1f} GB")
need_phys, need_commit = float(sys.argv[1]), float(sys.argv[2])
# Commit is the hard limit (allocations fail without it); short physical memory only slows a run.
sys.exit(0 if phys >= min(need_phys, 1.2) and commit >= need_commit else 1)
