using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace Geox
{
    class Program
    {
        static int Main(string[] args)
        {
            try
            {
                Console.OutputEncoding = Encoding.UTF8;
            }
            catch { }

            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            Directory.SetCurrentDirectory(baseDir);
            Console.Title = "Geox";

            string pythonExe = ResolvePython(baseDir);

            if (string.IsNullOrEmpty(pythonExe) || !File.Exists(pythonExe))
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("[Geox] Setting up Python environment...");
                Console.ResetColor();

                string bootstrap = Path.Combine(baseDir, "tools", "bootstrap_python.ps1");
                if (File.Exists(bootstrap))
                {
                    RunProcess("powershell.exe", string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\"", bootstrap));
                    string runtimePy = Path.Combine(baseDir, "runtime", "python.exe");
                    if (File.Exists(runtimePy))
                    {
                        string firstRun = Path.Combine(baseDir, "geox", "first_run.py");
                        if (File.Exists(firstRun))
                        {
                            RunProcess(runtimePy, string.Format("\"{0}\"", firstRun));
                        }
                        pythonExe = runtimePy;
                    }
                }
            }

            if (string.IsNullOrEmpty(pythonExe) || !File.Exists(pythonExe))
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("[Geox Error] Could not find or bootstrap a Python runtime.");
                Console.WriteLine("Please ensure Python 3.10+ is installed or internet access is available for bootstrap.");
                Console.ResetColor();
                Console.WriteLine("Press any key to exit...");
                Console.ReadKey();
                return 1;
            }

            // Build arguments
            StringBuilder pyArgs = new StringBuilder();
            pyArgs.Append("-m geox.launch");
            foreach (string arg in args)
            {
                if (arg.Contains(" "))
                {
                    pyArgs.AppendFormat(" \"{0}\"", arg);
                }
                else
                {
                    pyArgs.AppendFormat(" {0}", arg);
                }
            }

            return RunProcess(pythonExe, pyArgs.ToString());
        }

        static string ResolvePython(string baseDir)
        {
            string venvPy = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
            if (File.Exists(venvPy)) return venvPy;

            string runtimePy = Path.Combine(baseDir, "runtime", "python.exe");
            if (File.Exists(runtimePy)) return runtimePy;

            string systemPy = FindOnPath("python.exe");
            if (!string.IsNullOrEmpty(systemPy)) return systemPy;

            string pyLauncher = FindOnPath("py.exe");
            if (!string.IsNullOrEmpty(pyLauncher)) return pyLauncher;

            return null;
        }

        static string FindOnPath(string exeName)
        {
            string pathEnv = Environment.GetEnvironmentVariable("PATH");
            if (string.IsNullOrEmpty(pathEnv)) return null;

            string[] paths = pathEnv.Split(';');
            foreach (string p in paths)
            {
                try
                {
                    string trimmed = p.Trim();
                    if (!string.IsNullOrEmpty(trimmed))
                    {
                        string full = Path.Combine(trimmed, exeName);
                        if (File.Exists(full))
                        {
                            FileInfo fi = new FileInfo(full);
                            if (fi.Length > 0 && !full.ToLower().Contains("windowsapps"))
                            {
                                return full;
                            }
                        }
                    }
                }
                catch { }
            }
            return null;
        }

        static int RunProcess(string exe, string arguments)
        {
            ProcessStartInfo psi = new ProcessStartInfo(exe, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = false
            };

            using (Process proc = new Process())
            {
                proc.StartInfo = psi;
                proc.Start();
                proc.WaitForExit();
                return proc.ExitCode;
            }
        }
    }
}
