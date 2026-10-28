using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Principal;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("HikView Uninstaller")]
[assembly: AssemblyProduct("HikView")]
[assembly: AssemblyCompany("LibbyLamarr")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace HikViewUninstaller
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool silent = false;
            foreach (string a in args)
            {
                if (a.Equals("/S", StringComparison.OrdinalIgnoreCase) ||
                    a.Equals("/SILENT", StringComparison.OrdinalIgnoreCase))
                {
                    silent = true;
                }
            }

            if (!IsAdministrator())
            {
                try
                {
                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = Assembly.GetExecutingAssembly().Location;
                    psi.Arguments = string.Join(" ", args);
                    psi.Verb = "runas";
                    psi.UseShellExecute = true;
                    Process.Start(psi);
                }
                catch
                {
                    // User cancelled UAC
                }
                return;
            }

            if (!silent)
            {
                DialogResult dr = MessageBox.Show(
                    "Are you sure you want to completely remove HikView V1.0.0 and all of its components?",
                    "Uninstall HikView",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question
                );
                if (dr != DialogResult.Yes)
                {
                    return;
                }
            }

            string installDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);

            // Stop running HikView instances
            try
            {
                foreach (Process p in Process.GetProcessesByName("HikView"))
                {
                    try { p.Kill(); p.WaitForExit(3000); } catch { }
                }
            }
            catch { }

            // Remove Desktop shortcut
            try
            {
                string commonDesktop = Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory);
                string userDesktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string lnk1 = Path.Combine(commonDesktop, "HikView.lnk");
                string lnk2 = Path.Combine(userDesktop, "HikView.lnk");
                if (File.Exists(lnk1)) File.Delete(lnk1);
                if (File.Exists(lnk2)) File.Delete(lnk2);
            }
            catch { }

            // Remove Start Menu folder
            try
            {
                string commonStartMenu = Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms);
                string startMenuDir = Path.Combine(commonStartMenu, "HikView");
                if (Directory.Exists(startMenuDir))
                {
                    Directory.Delete(startMenuDir, true);
                }
            }
            catch { }

            // Remove Registry Uninstall entry
            try
            {
                Registry.LocalMachine.DeleteSubKeyTree(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\HikView", false);
            }
            catch { }

            if (!silent)
            {
                MessageBox.Show(
                    "HikView V1.0.0 has been uninstalled from your computer.",
                    "Uninstall Complete",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );
            }

            // Self-delete installation folder via background cmd process
            try
            {
                ProcessStartInfo cmd = new ProcessStartInfo();
                cmd.FileName = "cmd.exe";
                cmd.Arguments = "/C ping 127.0.0.1 -n 3 > nul & rmdir /s /q \"" + installDir + "\"";
                cmd.WindowStyle = ProcessWindowStyle.Hidden;
                cmd.CreateNoWindow = true;
                cmd.UseShellExecute = false;
                Process.Start(cmd);
            }
            catch { }
        }

        static bool IsAdministrator()
        {
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
            {
                WindowsPrincipal principal = new WindowsPrincipal(identity);
                return principal.IsInRole(WindowsBuiltInRole.Administrator);
            }
        }
    }
}
