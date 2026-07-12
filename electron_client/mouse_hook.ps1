param(
    [string]$Buttons = "XBUTTON1",
    [switch]$NoBlock,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class SideMouseHook
{
    private const int WH_MOUSE_LL = 14;
    private const int WM_MBUTTONDOWN = 0x0207;
    private const int WM_XBUTTONDOWN = 0x020B;
    private const int XBUTTON1 = 0x0001;
    private const int XBUTTON2 = 0x0002;

    private static readonly LowLevelMouseProc Proc = HookCallback;
    private static IntPtr hookId = IntPtr.Zero;

    public static readonly HashSet<string> TargetButtons = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    public static bool BlockTarget = true;
    public static event Action<string> ButtonPressed;

    public static void Start()
    {
        if (hookId != IntPtr.Zero)
        {
            return;
        }

        hookId = SetHook(Proc);
        if (hookId == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public static void Stop()
    {
        if (hookId == IntPtr.Zero)
        {
            return;
        }

        UnhookWindowsHookEx(hookId);
        hookId = IntPtr.Zero;
    }

    private static IntPtr SetHook(LowLevelMouseProc proc)
    {
        using (Process currentProcess = Process.GetCurrentProcess())
        using (ProcessModule currentModule = currentProcess.MainModule)
        {
            return SetWindowsHookEx(WH_MOUSE_LL, proc, GetModuleHandle(currentModule.ModuleName), 0);
        }
    }

    private delegate IntPtr LowLevelMouseProc(int nCode, IntPtr wParam, IntPtr lParam);

    private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode >= 0)
        {
            string button = "";
            if (wParam.ToInt32() == WM_MBUTTONDOWN)
            {
                button = "MBUTTON";
            }
            else if (wParam.ToInt32() == WM_XBUTTONDOWN)
            {
                MSLLHOOKSTRUCT data = (MSLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(MSLLHOOKSTRUCT));
                int xButton = (data.mouseData >> 16) & 0xffff;
                button = xButton == XBUTTON1 ? "XBUTTON1" : xButton == XBUTTON2 ? "XBUTTON2" : "";
            }

            if (!String.IsNullOrEmpty(button) && TargetButtons.Contains(button))
            {
                Action<string> handler = ButtonPressed;
                if (handler != null)
                {
                    handler(button);
                }

                if (BlockTarget)
                {
                    return new IntPtr(1);
                }
            }
        }

        return CallNextHookEx(hookId, nCode, wParam, lParam);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSLLHOOKSTRUCT
    {
        public POINT pt;
        public int mouseData;
        public int flags;
        public int time;
        public IntPtr dwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelMouseProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern IntPtr GetModuleHandle(string lpModuleName);
}
"@

$validButtons = @("MBUTTON", "XBUTTON1", "XBUTTON2")
$requestedButtons = @($Buttons.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim().ToUpperInvariant() })
if ($requestedButtons.Count -eq 0 -or @($requestedButtons | Where-Object { $_ -notin $validButtons }).Count -gt 0) {
    throw "Unsupported mouse shortcut button."
}
foreach ($button in $requestedButtons) {
    [void][SideMouseHook]::TargetButtons.Add($button)
}
[SideMouseHook]::BlockTarget = -not $NoBlock.IsPresent

if ($SelfTest) {
    return
}

$handler = [System.Action[string]]{
    param([string]$pressedButton)

    [Console]::Out.WriteLine($pressedButton)
    [Console]::Out.Flush()
}

[SideMouseHook]::add_ButtonPressed($handler)

try {
    [SideMouseHook]::Start()
    [System.Windows.Forms.Application]::Run()
}
finally {
    [SideMouseHook]::Stop()
}
