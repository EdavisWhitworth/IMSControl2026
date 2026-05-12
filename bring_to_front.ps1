Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    
    public class WindowHelper {
        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
        
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
        
        [DllImport("user32.dll")]
        public static extern bool IsIconic(IntPtr hWnd);
        
        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        
        public static void BringWindowToFront(string windowTitle) {
            IntPtr hWnd = FindWindow(null, windowTitle);
            if (hWnd != IntPtr.Zero) {
                if (IsIconic(hWnd)) {
                    ShowWindow(hWnd, 9); // SW_RESTORE
                }
                SetForegroundWindow(hWnd);
                Write-Host "✓ Successfully brought '$windowTitle' to foreground"
            } else {
                Write-Host "✗ Window '$windowTitle' not found"
            }
        }
    }
"@

[WindowHelper]::BringWindowToFront("IMS Control")
