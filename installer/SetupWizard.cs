using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("HikView V1.0.0 Setup")]
[assembly: AssemblyDescription("HikView V1.0.0 Windows Installer")]
[assembly: AssemblyProduct("HikView")]
[assembly: AssemblyCompany("LibbyLamarr")]
[assembly: AssemblyCopyright("Copyright (c) 2026 LibbyLamarr — MIT License")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace HikViewSetup
{
    public class SetupForm : Form
    {
        private TextBox txtInstallDir;
        private Button btnBrowse;
        private CheckBox chkDesktopShortcut;
        private CheckBox chkStartMenuShortcut;
        private CheckBox chkLaunchAfter;
        private ProgressBar progressBar;
        private Label lblStatus;
        private Button btnInstall;
        private Button btnCancel;
        private bool isInstalling = false;
        private bool installFinished = false;

        public SetupForm()
        {
            this.Text = "HikView V1.0.0 Setup";
            this.Size = new Size(560, 430);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(20, 24, 32);
            this.ForeColor = Color.FromArgb(228, 232, 240);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            BuildUI();
        }

        private void BuildUI()
        {
            // Top Header Banner
            Panel headerPanel = new Panel();
            headerPanel.Dock = DockStyle.Top;
            headerPanel.Height = 76;
            headerPanel.BackColor = Color.FromArgb(26, 32, 44);
            this.Controls.Add(headerPanel);

            Panel accentLine = new Panel();
            accentLine.Dock = DockStyle.Bottom;
            accentLine.Height = 2;
            accentLine.BackColor = Color.FromArgb(224, 62, 62);
            headerPanel.Controls.Add(accentLine);

            Label lblTitle = new Label();
            lblTitle.Text = "HikView V1.0.0 — Setup Wizard";
            lblTitle.Font = new Font("Segoe UI", 14f, FontStyle.Bold);
            lblTitle.ForeColor = Color.White;
            lblTitle.Location = new Point(20, 14);
            lblTitle.AutoSize = true;
            headerPanel.Controls.Add(lblTitle);

            Label lblSub = new Label();
            lblSub.Text = "Lightweight NVR & IP Camera Viewer • Developed by LibbyLamarr (MIT License)";
            lblSub.Font = new Font("Segoe UI", 9f, FontStyle.Regular);
            lblSub.ForeColor = Color.FromArgb(160, 172, 192);
            lblSub.Location = new Point(22, 44);
            lblSub.AutoSize = true;
            headerPanel.Controls.Add(lblSub);

            // Destination Folder
            Label lblDir = new Label();
            lblDir.Text = "Destination Installation Folder:";
            lblDir.Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            lblDir.Location = new Point(22, 94);
            lblDir.AutoSize = true;
            this.Controls.Add(lblDir);

            string defaultProgramFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            txtInstallDir = new TextBox();
            txtInstallDir.Text = Path.Combine(defaultProgramFiles, "HikView");
            txtInstallDir.Location = new Point(22, 118);
            txtInstallDir.Size = new Size(405, 26);
            txtInstallDir.BackColor = Color.FromArgb(14, 18, 26);
            txtInstallDir.ForeColor = Color.White;
            txtInstallDir.BorderStyle = BorderStyle.FixedSingle;
            this.Controls.Add(txtInstallDir);

            btnBrowse = new Button();
            btnBrowse.Text = "Browse...";
            btnBrowse.Location = new Point(435, 116);
            btnBrowse.Size = new Size(88, 27);
            btnBrowse.FlatStyle = FlatStyle.Flat;
            btnBrowse.BackColor = Color.FromArgb(37, 44, 59);
            btnBrowse.ForeColor = Color.White;
            btnBrowse.Click += OnBrowseClicked;
            this.Controls.Add(btnBrowse);

            // Options
            Label lblOpts = new Label();
            lblOpts.Text = "Installation Options:";
            lblOpts.Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            lblOpts.Location = new Point(22, 160);
            lblOpts.AutoSize = true;
            this.Controls.Add(lblOpts);

            chkDesktopShortcut = new CheckBox();
            chkDesktopShortcut.Text = "Create a Desktop shortcut";
            chkDesktopShortcut.Checked = true;
            chkDesktopShortcut.Location = new Point(26, 186);
            chkDesktopShortcut.AutoSize = true;
            this.Controls.Add(chkDesktopShortcut);

            chkStartMenuShortcut = new CheckBox();
            chkStartMenuShortcut.Text = "Create Start Menu shortcuts (Program & Uninstaller)";
            chkStartMenuShortcut.Checked = true;
            chkStartMenuShortcut.Location = new Point(26, 212);
            chkStartMenuShortcut.AutoSize = true;
            this.Controls.Add(chkStartMenuShortcut);

            chkLaunchAfter = new CheckBox();
            chkLaunchAfter.Text = "Launch HikView after installation completes";
            chkLaunchAfter.Checked = true;
            chkLaunchAfter.Location = new Point(26, 238);
            chkLaunchAfter.AutoSize = true;
            this.Controls.Add(chkLaunchAfter);

            // Progress section
            lblStatus = new Label();
            lblStatus.Text = "Click 'Install' to install HikView V1.0.0 to your computer.";
            lblStatus.ForeColor = Color.FromArgb(154, 164, 184);
            lblStatus.Location = new Point(22, 278);
            lblStatus.Size = new Size(500, 22);
            this.Controls.Add(lblStatus);

            progressBar = new ProgressBar();
            progressBar.Location = new Point(22, 304);
            progressBar.Size = new Size(501, 22);
            progressBar.Minimum = 0;
            progressBar.Maximum = 100;
            progressBar.Value = 0;
            this.Controls.Add(progressBar);

            // Bottom buttons
            btnInstall = new Button();
            btnInstall.Text = "Install";
            btnInstall.Location = new Point(316, 344);
            btnInstall.Size = new Size(100, 32);
            btnInstall.FlatStyle = FlatStyle.Flat;
            btnInstall.BackColor = Color.FromArgb(224, 62, 62);
            btnInstall.ForeColor = Color.White;
            btnInstall.Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            btnInstall.Click += OnInstallClicked;
            this.Controls.Add(btnInstall);

            btnCancel = new Button();
            btnCancel.Text = "Cancel";
            btnCancel.Location = new Point(423, 344);
            btnCancel.Size = new Size(100, 32);
            btnCancel.FlatStyle = FlatStyle.Flat;
            btnCancel.BackColor = Color.FromArgb(37, 44, 59);
            btnCancel.ForeColor = Color.White;
            btnCancel.Click += (s, e) => { if (!isInstalling) this.Close(); };
            this.Controls.Add(btnCancel);
        }

        private void OnBrowseClicked(object sender, EventArgs e)
        {
            using (FolderBrowserDialog fbd = new FolderBrowserDialog())
            {
                fbd.Description = "Select the destination folder where HikView will be installed:";
                fbd.SelectedPath = txtInstallDir.Text;
                if (fbd.ShowDialog(this) == DialogResult.OK)
                {
                    string selected = fbd.SelectedPath;
                    if (!selected.EndsWith("HikView", StringComparison.OrdinalIgnoreCase))
                    {
                        selected = Path.Combine(selected, "HikView");
                    }
                    txtInstallDir.Text = selected;
                }
            }
        }

        private void OnInstallClicked(object sender, EventArgs e)
        {
            if (installFinished)
            {
                string exePath = Path.Combine(txtInstallDir.Text.Trim(), "HikView.exe");
                if (chkLaunchAfter.Checked && File.Exists(exePath))
                {
                    try
                    {
                        ProcessStartInfo psi = new ProcessStartInfo(exePath);
                        psi.WorkingDirectory = txtInstallDir.Text.Trim();
                        psi.UseShellExecute = true;
                        Process.Start(psi);
                    }
                    catch { }
                }
                this.Close();
                return;
            }

            string targetDir = txtInstallDir.Text.Trim();
            if (string.IsNullOrEmpty(targetDir))
            {
                MessageBox.Show(this, "Please select a valid installation directory.", "HikView Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            isInstalling = true;
            txtInstallDir.Enabled = false;
            btnBrowse.Enabled = false;
            chkDesktopShortcut.Enabled = false;
            chkStartMenuShortcut.Enabled = false;
            btnInstall.Enabled = false;
            btnCancel.Enabled = false;

            bool makeDesktop = chkDesktopShortcut.Checked;
            bool makeStartMenu = chkStartMenuShortcut.Checked;

            Thread worker = new Thread(() => RunInstallation(targetDir, makeDesktop, makeStartMenu));
            worker.IsBackground = true;
            worker.Start();
        }

        private void UpdateProgress(int pct, string message)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<int, string>(UpdateProgress), pct, message);
                return;
            }
            progressBar.Value = Math.Max(0, Math.Min(100, pct));
            lblStatus.Text = message;
        }

        private void OnInstallationDone(bool success, string errorMsg)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<bool, string>(OnInstallationDone), success, errorMsg);
                return;
            }
            isInstalling = false;
            if (success)
            {
                installFinished = true;
                progressBar.Value = 100;
                lblStatus.ForeColor = Color.FromArgb(46, 204, 113);
                lblStatus.Text = "Installation complete! Click 'Finish' to exit setup.";
                btnInstall.Text = "Finish";
                btnInstall.Enabled = true;
            }
            else
            {
                lblStatus.ForeColor = Color.FromArgb(240, 101, 101);
                lblStatus.Text = "Installation failed: " + errorMsg;
                btnCancel.Enabled = true;
                MessageBox.Show(this, "Failed to install HikView:\n\n" + errorMsg, "Installation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void RunInstallation(string targetDir, bool makeDesktop, bool makeStartMenu)
        {
            try
            {
                UpdateProgress(5, "Stopping any running HikView processes...");
                foreach (Process p in Process.GetProcessesByName("HikView"))
                {
                    try { p.Kill(); p.WaitForExit(3000); } catch { }
                }

                UpdateProgress(10, "Preparing installation directory...");
                if (!Directory.Exists(targetDir))
                {
                    Directory.CreateDirectory(targetDir);
                }

                UpdateProgress(15, "Opening embedded installation archive...");
                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream resStream = asm.GetManifestResourceStream("HikViewPayload.zip"))
                {
                    if (resStream == null)
                    {
                        throw new Exception("Embedded application payload (HikViewPayload.zip) was not found.");
                    }

                    using (ZipArchive archive = new ZipArchive(resStream, ZipArchiveMode.Read))
                    {
                        int total = archive.Entries.Count;
                        int count = 0;

                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            count++;
                            string relPath = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                            // Strip leading "HikView\" prefix if present inside zip
                            if (relPath.StartsWith("HikView" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                            {
                                relPath = relPath.Substring(("HikView" + Path.DirectorySeparatorChar).Length);
                            }
                            if (string.IsNullOrEmpty(relPath))
                            {
                                continue;
                            }

                            string destPath = Path.Combine(targetDir, relPath);
                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                Directory.CreateDirectory(destPath);
                                continue;
                            }

                            string destFolder = Path.GetDirectoryName(destPath);
                            if (!string.IsNullOrEmpty(destFolder) && !Directory.Exists(destFolder))
                            {
                                Directory.CreateDirectory(destFolder);
                            }

                            entry.ExtractToFile(destPath, true);

                            if (count % 10 == 0 || count == total)
                            {
                                int pct = 15 + (int)((count / (double)Math.Max(1, total)) * 70.0);
                                UpdateProgress(pct, "Installing: " + entry.Name + " (" + count + "/" + total + ")");
                            }
                        }
                    }
                }

                string mainExe = Path.Combine(targetDir, "HikView.exe");
                string uninstallExe = Path.Combine(targetDir, "Uninstall-HikView.exe");

                if (makeDesktop)
                {
                    UpdateProgress(88, "Creating Desktop shortcut...");
                    string desktopDir = Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory);
                    CreateShortcut(Path.Combine(desktopDir, "HikView.lnk"), mainExe, targetDir, "HikView — NVR & IP Camera Viewer");
                }

                if (makeStartMenu)
                {
                    UpdateProgress(92, "Creating Start Menu shortcuts...");
                    string programsDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms), "HikView");
                    if (!Directory.Exists(programsDir))
                    {
                        Directory.CreateDirectory(programsDir);
                    }
                    CreateShortcut(Path.Combine(programsDir, "HikView.lnk"), mainExe, targetDir, "HikView — NVR & IP Camera Viewer");
                    if (File.Exists(uninstallExe))
                    {
                        CreateShortcut(Path.Combine(programsDir, "Uninstall HikView.lnk"), uninstallExe, targetDir, "Uninstall HikView");
                    }
                }

                UpdateProgress(96, "Registering application in Windows Installed Apps...");
                RegisterUninstaller(targetDir, mainExe, uninstallExe);

                OnInstallationDone(true, null);
            }
            catch (Exception ex)
            {
                OnInstallationDone(false, ex.Message);
            }
        }

        public static void CreateShortcut(string shortcutPath, string targetExe, string workingDir, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcutPath });
                Type scType = shortcut.GetType();
                scType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe });
                scType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDir });
                scType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                scType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe + ",0" });
                scType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch { }
        }

        public static void RegisterUninstaller(string installDir, string mainExe, string uninstallExe)
        {
            try
            {
                using (RegistryKey key = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\HikView"))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "HikView");
                        key.SetValue("DisplayVersion", "1.0.0");
                        key.SetValue("Publisher", "LibbyLamarr");
                        key.SetValue("DisplayIcon", mainExe);
                        key.SetValue("InstallLocation", installDir);
                        key.SetValue("UninstallString", "\"" + uninstallExe + "\"");
                        key.SetValue("QuietUninstallString", "\"" + uninstallExe + "\" /S");
                        key.SetValue("URLInfoAbout", "https://github.com/LibbyLamarr/HikView");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }
    }

    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

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
                    MessageBox.Show(
                        "Administrator privileges are required to install HikView into Program Files.",
                        "HikView V1.0.0 Setup",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning
                    );
                }
                return;
            }

            Application.Run(new SetupForm());
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
