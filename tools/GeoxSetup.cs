using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace GeoxSetup
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            // Set TLS 1.2 and TLS 1.3
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072 | (SecurityProtocolType)12288 | SecurityProtocolType.Tls12;

            bool silent = false;
            string targetDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Geox");

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].Trim().ToLowerInvariant();
                if (a == "/s" || a == "/silent" || a == "-silent" || a == "--silent")
                {
                    silent = true;
                }
                else if (a.StartsWith("/dir=") || a.StartsWith("-dir="))
                {
                    targetDir = args[i].Substring(args[i].IndexOf('=') + 1).Trim('"', ' ');
                }
            }

            if (silent)
            {
                RunSilentInstall(targetDir);
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm(targetDir));
        }

        static void RunSilentInstall(string targetDir)
        {
            try
            {
                InstallerEngine engine = new InstallerEngine(targetDir, true, true, false);
                engine.ExecuteSync();
            }
            catch { }
        }
    }

    public class InstallerForm : Form
    {
        private TextBox txtDir;
        private Button btnBrowse;
        private CheckBox chkDesktop;
        private CheckBox chkStartMenu;
        private CheckBox chkLaunch;
        private Button btnInstall;
        private ProgressBar progressBar;
        private Label lblStatus;
        private InstallerEngine engine;

        public InstallerForm(string defaultDir)
        {
            this.Text = "Geox Setup";
            this.Size = new Size(540, 420);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(17, 17, 21);
            this.ForeColor = Color.FromArgb(244, 244, 245);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            // Header Banner
            Panel pnlHeader = new Panel
            {
                Dock = DockStyle.Top,
                Height = 84,
                BackColor = Color.FromArgb(9, 9, 11)
            };
            this.Controls.Add(pnlHeader);

            Label lblTitle = new Label
            {
                Text = "GEOX",
                Font = new Font("Segoe UI", 18f, FontStyle.Bold),
                ForeColor = Color.FromArgb(34, 197, 94),
                Location = new Point(24, 14),
                AutoSize = true
            };
            pnlHeader.Controls.Add(lblTitle);

            Label lblSub = new Label
            {
                Text = "Precision GPS location spoofer for iOS & Android",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(161, 161, 170),
                Location = new Point(26, 48),
                AutoSize = true
            };
            pnlHeader.Controls.Add(lblSub);

            // Install Directory Controls
            Label lblDir = new Label
            {
                Text = "Destination Folder:",
                Location = new Point(24, 104),
                AutoSize = true,
                ForeColor = Color.FromArgb(212, 212, 216)
            };
            this.Controls.Add(lblDir);

            txtDir = new TextBox
            {
                Text = defaultDir,
                Location = new Point(24, 128),
                Width = 370,
                BackColor = Color.FromArgb(26, 26, 32),
                ForeColor = Color.FromArgb(244, 244, 245),
                BorderStyle = BorderStyle.FixedSingle
            };
            this.Controls.Add(txtDir);

            btnBrowse = new Button
            {
                Text = "Browse...",
                Location = new Point(404, 126),
                Width = 92,
                Height = 26,
                BackColor = Color.FromArgb(39, 39, 48),
                ForeColor = Color.FromArgb(244, 244, 245),
                FlatStyle = FlatStyle.Flat
            };
            btnBrowse.FlatAppearance.BorderColor = Color.FromArgb(63, 63, 70);
            btnBrowse.Click += (s, e) =>
            {
                using (FolderBrowserDialog fbd = new FolderBrowserDialog())
                {
                    fbd.SelectedPath = txtDir.Text;
                    if (fbd.ShowDialog() == DialogResult.OK)
                    {
                        txtDir.Text = fbd.SelectedPath;
                    }
                }
            };
            this.Controls.Add(btnBrowse);

            // Checkboxes
            chkDesktop = new CheckBox
            {
                Text = "Create Desktop shortcut",
                Checked = true,
                Location = new Point(26, 170),
                AutoSize = true,
                ForeColor = Color.FromArgb(212, 212, 216)
            };
            this.Controls.Add(chkDesktop);

            chkStartMenu = new CheckBox
            {
                Text = "Create Start Menu shortcut",
                Checked = true,
                Location = new Point(26, 198),
                AutoSize = true,
                ForeColor = Color.FromArgb(212, 212, 216)
            };
            this.Controls.Add(chkStartMenu);

            chkLaunch = new CheckBox
            {
                Text = "Launch Geox after installation",
                Checked = true,
                Location = new Point(26, 226),
                AutoSize = true,
                ForeColor = Color.FromArgb(212, 212, 216)
            };
            this.Controls.Add(chkLaunch);

            // Progress bar & Status
            progressBar = new ProgressBar
            {
                Location = new Point(24, 266),
                Width = 472,
                Height = 18,
                Visible = false
            };
            this.Controls.Add(progressBar);

            lblStatus = new Label
            {
                Text = "Ready to install.",
                Location = new Point(24, 290),
                Width = 472,
                Height = 24,
                ForeColor = Color.FromArgb(161, 161, 170)
            };
            this.Controls.Add(lblStatus);

            // Install Button
            btnInstall = new Button
            {
                Text = "Install Geox",
                Location = new Point(24, 324),
                Width = 472,
                Height = 38,
                BackColor = Color.FromArgb(34, 197, 94),
                ForeColor = Color.Black,
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                FlatStyle = FlatStyle.Flat,
                Cursor = Cursors.Hand
            };
            btnInstall.FlatAppearance.BorderSize = 0;
            btnInstall.Click += StartInstallation;
            this.Controls.Add(btnInstall);
        }

        private void StartInstallation(object sender, EventArgs e)
        {
            string installPath = txtDir.Text.Trim();
            if (string.IsNullOrEmpty(installPath))
            {
                MessageBox.Show("Please choose a destination folder.", "Geox Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            btnInstall.Enabled = false;
            btnBrowse.Enabled = false;
            txtDir.Enabled = false;
            chkDesktop.Enabled = false;
            chkStartMenu.Enabled = false;
            chkLaunch.Enabled = false;
            progressBar.Visible = true;
            progressBar.Value = 0;

            engine = new InstallerEngine(installPath, chkDesktop.Checked, chkStartMenu.Checked, chkLaunch.Checked);
            engine.StatusChanged += (s, msg) =>
            {
                if (this.InvokeRequired)
                {
                    this.Invoke(new Action(() => lblStatus.Text = msg));
                }
                else
                {
                    lblStatus.Text = msg;
                }
            };
            engine.ProgressChanged += (s, pct) =>
            {
                if (this.InvokeRequired)
                {
                    this.Invoke(new Action(() => progressBar.Value = Math.Min(100, Math.Max(0, pct))));
                }
                else
                {
                    progressBar.Value = Math.Min(100, Math.Max(0, pct));
                }
            };
            engine.Completed += (s, success, err) =>
            {
                if (this.InvokeRequired)
                {
                    this.Invoke(new Action(() => FinishInstallation(success, err)));
                }
                else
                {
                    FinishInstallation(success, err);
                }
            };

            Thread t = new Thread(new ThreadStart(engine.Execute));
            t.IsBackground = true;
            t.Start();
        }

        private void FinishInstallation(bool success, string err)
        {
            if (success)
            {
                lblStatus.Text = "Installation completed successfully.";
                lblStatus.ForeColor = Color.FromArgb(34, 197, 94);
                progressBar.Value = 100;
                btnInstall.Text = "Close";
                btnInstall.BackColor = Color.FromArgb(39, 39, 48);
                btnInstall.ForeColor = Color.White;
                btnInstall.Enabled = true;
                btnInstall.Click -= StartInstallation;
                btnInstall.Click += (s, e) => this.Close();

                if (chkLaunch.Checked)
                {
                    engine.LaunchApp();
                    this.Close();
                }
            }
            else
            {
                lblStatus.Text = "Error: " + err;
                lblStatus.ForeColor = Color.FromArgb(239, 68, 68);
                btnInstall.Enabled = true;
                btnInstall.Text = "Retry";
            }
        }
    }

    public class InstallerEngine
    {
        public event EventHandler<string> StatusChanged;
        public event EventHandler<int> ProgressChanged;
        public event Action<object, bool, string> Completed;

        private readonly string installDir;
        private readonly bool createDesktop;
        private readonly bool createStartMenu;
        private readonly bool launchAfter;

        public InstallerEngine(string dir, bool desktop, bool startMenu, bool launch)
        {
            installDir = dir;
            createDesktop = desktop;
            createStartMenu = startMenu;
            launchAfter = launch;
        }

        public void Execute()
        {
            try
            {
                ExecuteSync();
                if (Completed != null) Completed(this, true, null);
            }
            catch (Exception ex)
            {
                if (Completed != null) Completed(this, false, ex.Message);
            }
        }

        public void ExecuteSync()
        {
            ReportStatus("Preparing destination directory...", 5);
            if (!Directory.Exists(installDir))
            {
                Directory.CreateDirectory(installDir);
            }

            string zipPath = Path.Combine(Path.GetTempPath(), "geox-setup-" + Guid.NewGuid().ToString("N") + ".zip");
            string extractPath = Path.Combine(Path.GetTempPath(), "geox-unpacked-" + Guid.NewGuid().ToString("N"));

            try
            {
                ReportStatus("Downloading Geox from GitHub...", 15);
                using (WebClient client = new WebClient())
                {
                    client.Headers.Add("User-Agent", "Geox-Setup-Installer");
                    client.DownloadProgressChanged += (s, e) =>
                    {
                        int scaled = 15 + (int)(e.ProgressPercentage * 0.40);
                        if (ProgressChanged != null) ProgressChanged(this, scaled);
                    };
                    client.DownloadFile(new Uri("https://github.com/arx33d/Geox/archive/refs/heads/main.zip"), zipPath);
                }

                ReportStatus("Extracting files...", 60);
                if (Directory.Exists(extractPath))
                {
                    Directory.Delete(extractPath, true);
                }
                ZipFile.ExtractToDirectory(zipPath, extractPath);

                // GitHub zip archives contain a root directory like Geox-main
                string[] subdirs = Directory.GetDirectories(extractPath);
                string sourceFolder = subdirs.Length > 0 ? subdirs[0] : extractPath;

                CopyDirectory(sourceFolder, installDir);
                ReportStatus("Files extracted.", 75);
            }
            finally
            {
                try { if (File.Exists(zipPath)) File.Delete(zipPath); } catch { }
                try { if (Directory.Exists(extractPath)) Directory.Delete(extractPath, true); } catch { }
            }

            // Setup Python environment
            ReportStatus("Configuring runtime environment...", 80);
            string venvPy = Path.Combine(installDir, ".venv", "Scripts", "python.exe");
            string runtimePy = Path.Combine(installDir, "runtime", "python.exe");

            if (!File.Exists(venvPy) && !File.Exists(runtimePy))
            {
                // Run bootstrap to get embeddable python runtime
                string bootstrap = Path.Combine(installDir, "tools", "bootstrap_python.ps1");
                if (File.Exists(bootstrap))
                {
                    RunProcess("powershell.exe", string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\"", bootstrap));
                }
            }

            // Compile Geox.exe if needed
            ReportStatus("Configuring native launcher...", 88);
            string exePath = Path.Combine(installDir, "Geox.exe");
            string csc = @"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe";
            string launcherCs = Path.Combine(installDir, "tools", "GeoxLauncher.cs");
            string iconPath = Path.Combine(installDir, "tools", "geox.ico");

            if (File.Exists(csc) && File.Exists(launcherCs))
            {
                string iconArg = File.Exists(iconPath) ? string.Format("/win32icon:\"{0}\"", iconPath) : "";
                string args = string.Format("/nologo /target:exe /out:\"{0}\" {1} \"{2}\"", exePath, iconArg, launcherCs);
                RunProcess(csc, args);
            }

            // Shortcuts
            ReportStatus("Creating application shortcuts...", 95);
            string targetLaunch = File.Exists(exePath) ? exePath : Path.Combine(installDir, "run_geox.bat");

            if (createDesktop)
            {
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
                CreateShortcut(Path.Combine(desktop, "Geox.lnk"), targetLaunch, installDir, iconPath, "Geox GPS Location Spoofer");
            }

            if (createStartMenu)
            {
                string startPrograms = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                CreateShortcut(Path.Combine(startPrograms, "Geox.lnk"), targetLaunch, installDir, iconPath, "Geox GPS Location Spoofer");
            }

            ReportStatus("Ready!", 100);
        }

        public void LaunchApp()
        {
            string exePath = Path.Combine(installDir, "Geox.exe");
            string target = File.Exists(exePath) ? exePath : Path.Combine(installDir, "run_geox.bat");
            if (File.Exists(target))
            {
                ProcessStartInfo psi = new ProcessStartInfo(target)
                {
                    WorkingDirectory = installDir,
                    UseShellExecute = true
                };
                Process.Start(psi);
            }
        }

        private void ReportStatus(string text, int percent)
        {
            if (StatusChanged != null) StatusChanged(this, text);
            if (ProgressChanged != null) ProgressChanged(this, percent);
        }

        private static void CopyDirectory(string sourceDir, string targetDir)
        {
            Directory.CreateDirectory(targetDir);
            foreach (string file in Directory.GetFiles(sourceDir))
            {
                string destFile = Path.Combine(targetDir, Path.GetFileName(file));
                File.Copy(file, destFile, true);
            }
            foreach (string dir in Directory.GetDirectories(sourceDir))
            {
                string destDir = Path.Combine(targetDir, Path.GetFileName(dir));
                CopyDirectory(dir, destDir);
            }
        }

        private static void CreateShortcut(string shortcutPath, string targetPath, string workDir, string iconPath, string desc)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                dynamic shell = Activator.CreateInstance(shellType);
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = targetPath;
                shortcut.WorkingDirectory = workDir;
                if (!string.IsNullOrEmpty(iconPath) && File.Exists(iconPath))
                {
                    shortcut.IconLocation = iconPath;
                }
                shortcut.Description = desc;
                shortcut.Save();
            }
            catch { }
        }

        private static void RunProcess(string exe, string args)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(exe, args)
                {
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                using (Process p = Process.Start(psi))
                {
                    p.WaitForExit(30000);
                }
            }
            catch { }
        }
    }
}
