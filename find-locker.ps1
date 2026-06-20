# Identify which process holds a file open (Windows Restart Manager).
# Usage: powershell -File find-locker.ps1 "<path>"
param([Parameter(Mandatory=$true)][string]$Target)

$src = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class LockFinder {
  [StructLayout(LayoutKind.Sequential)] struct UP { public int pid; public System.Runtime.InteropServices.ComTypes.FILETIME t; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct PI {
    public UP Process;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string app;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=64)]  public string svc;
    public int appType; public uint status; public uint tsId; [MarshalAs(UnmanagedType.Bool)] public bool restartable;
  }
  [DllImport("rstrtmgr.dll", CharSet=CharSet.Unicode)] static extern int RmStartSession(out uint h, int f, string k);
  [DllImport("rstrtmgr.dll")] static extern int RmEndSession(uint h);
  [DllImport("rstrtmgr.dll", CharSet=CharSet.Unicode)] static extern int RmRegisterResources(uint h, uint nf, string[] f, uint na, IntPtr a, uint ns, string[] s);
  [DllImport("rstrtmgr.dll")] static extern int RmGetList(uint h, out uint need, ref uint cnt, [In,Out] PI[] info, ref uint reason);
  public static List<string> Who(string path){
    var res = new List<string>(); uint h;
    if (RmStartSession(out h, 0, Guid.NewGuid().ToString()) != 0) return res;
    try {
      if (RmRegisterResources(h, 1, new[]{path}, 0, IntPtr.Zero, 0, null) != 0) return res;
      uint need = 0, cnt = 0, reason = 0;
      RmGetList(h, out need, ref cnt, null, ref reason);
      if (need == 0) return res;
      var arr = new PI[need]; cnt = need;
      if (RmGetList(h, out need, ref cnt, arr, ref reason) != 0) return res;
      for (uint i = 0; i < cnt; i++) res.Add(arr[i].app + "  (pid " + arr[i].Process.pid + ", type " + arr[i].appType + ")");
    } finally { RmEndSession(h); }
    return res;
  }
}
"@
Add-Type -TypeDefinition $src -Language CSharp
$who = [LockFinder]::Who($Target)
if ($who.Count) { "HOLDERS of: $Target"; $who | ForEach-Object { "  - $_" } }
else { "no holder reported (lock may have just cleared)" }
