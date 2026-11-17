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

            string pythonExe = EnsurePython(baseDir);

            if (string.IsNullOrEmpty(pythonExe) || !File.Exists(pythonExe))
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("\n[Geox Error] Could not find or configure a usable Python environment.");
                Console.WriteLine("Please ensure Python 3.10+ is installed or internet access is available for setup.");
                Console.ResetColor();
                Console.WriteLine("Press any key to exit...");
                try { Console.ReadKey(); } catch { }
                return 1;
            }

            // Build arguments
            StringBuilder pyArgs = new StringBuilder();
            if (args.Length == 0)
            {
                pyArgs.Append("-m geox.server");
            }
            else
            {
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
            }

            int exitCode = RunProcess(pythonExe, pyArgs.ToString(), false);
            if (exitCode != 0)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine(string.Format("\n[Geox] Application exited with code {0}.", exitCode));
                Console.ResetColor();
                Console.WriteLine("Press any key to close this window...");
                try
                {
                    Console.ReadKey();
                }
                catch { }
            }
            return exitCode;
        }

        static string EnsurePython(string baseDir)
        {
            string venvPy = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
            string runtimePy = Path.Combine(baseDir, "runtime", "python.exe");
            string firstRun = Path.Combine(baseDir, "geox", "first_run.py");
            string reqFile = Path.Combine(baseDir, "requirements.txt");

            // 1. Existing venv
            if (File.Exists(venvPy))
            {
                if (VerifyPython(venvPy)) return venvPy;

                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("[Geox] Verifying and updating dependencies in virtual environment...");
                Console.ResetColor();
                InstallDependencies(venvPy, firstRun, reqFile);
                if (VerifyPython(venvPy)) return venvPy;
            }

            // 2. Existing private runtime
            if (File.Exists(runtimePy))
            {
                if (VerifyPython(runtimePy)) return runtimePy;

                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("[Geox] Verifying and updating dependencies in runtime...");
                Console.ResetColor();
                InstallDependencies(runtimePy, firstRun, reqFile);
                if (VerifyPython(runtimePy)) return runtimePy;
            }

            // 3. Fresh installation: try creating a .venv with system Python
            string systemPy = FindSystemPython();
            if (!string.IsNullOrEmpty(systemPy))
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("[Geox] First-time setup: configuring Python environment...");
                Console.ResetColor();

                int code = RunProcess(systemPy, "-m venv .venv", false);
                if (code == 0 && File.Exists(venvPy))
                {
                    InstallDependencies(venvPy, firstRun, reqFile);
                    if (VerifyPython(venvPy)) return venvPy;
                }
            }

            // 4. Fallback: bootstrap private Python runtime via PowerShell
            string bootstrap = Path.Combine(baseDir, "tools", "bootstrap_python.ps1");
            if (File.Exists(bootstrap))
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("[Geox] Downloading self-contained Python runtime (~11 MB)...");
                Console.ResetColor();

                RunProcess("powershell.exe", string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\"", bootstrap), false);
                if (File.Exists(runtimePy))
                {
                    InstallDependencies(runtimePy, firstRun, reqFile);
                    if (VerifyPython(runtimePy)) return runtimePy;
                }
            }

            // 5. Final fallback: does system Python happen to have all dependencies installed globally?
            if (!string.IsNullOrEmpty(systemPy) && VerifyPython(systemPy))
            {
                return systemPy;
            }

            return null;
        }

        static bool VerifyPython(string pyExe)
        {
            if (string.IsNullOrEmpty(pyExe) || !File.Exists(pyExe)) return false;
            try
            {
                return RunProcess(pyExe, "-c \"import flask, requests, pymobiledevice3\"", true) == 0;
            }
            catch
            {
                return false;
            }
        }

        static void InstallDependencies(string pyExe, string firstRun, string reqFile)
        {
            if (File.Exists(firstRun))
            {
                RunProcess(pyExe, string.Format("\"{0}\"", firstRun), false);
            }
            else if (File.Exists(reqFile))
            {
                RunProcess(pyExe, string.Format("-m pip install --quiet --disable-pip-version-check -r \"{0}\"", reqFile), false);
            }
        }

        static string FindSystemPython()
        {
            string systemPy = FindOnPath("python.exe");
            if (!string.IsNullOrEmpty(systemPy) && TestPythonUsable(systemPy)) return systemPy;

            string pyLauncher = FindOnPath("py.exe");
            if (!string.IsNullOrEmpty(pyLauncher) && TestPythonUsable(pyLauncher)) return pyLauncher;

            return null;
        }

        static bool TestPythonUsable(string pyExe)
        {
            try
            {
                return RunProcess(pyExe, "-c \"import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)\"", true) == 0;
            }
            catch
            {
                return false;
            }
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

        static int RunProcess(string exe, string arguments, bool hideWindow)
        {
            ProcessStartInfo psi = new ProcessStartInfo(exe, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = hideWindow
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
