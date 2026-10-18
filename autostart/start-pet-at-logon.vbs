' xinyuehu (Hsin Moon Fox) desktop pet - silent logon launcher for the watchdog.
'
' install-autostart.cmd copies this file into the user's Startup folder,
' substituting the two placeholders above with absolute paths. The copy cannot
' find anything by its own location. Keep it ASCII-only.
'
' Note on the interpreter: %DSH_HOME% is NOT set in a fresh logon environment,
' so the DSH path must be baked in. Falling back to a bare "python.exe" is
' actively harmful here - it picks up whatever Python is first on PATH (on this
' machine a Microsoft Store runtime) which lacks Pillow/numpy, so every pet
' launch fails and the watchdog restarts it forever.

Option Explicit

Dim fso, shell, root, py, watchdog, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = "__PACKAGE_ROOT__"
py = "__PYTHON_EXE__"
watchdog = fso.BuildPath(root, "run_pet_watchdog.py")

If Not fso.FileExists(watchdog) Then
  WScript.Quit 1
End If

If Not fso.FileExists(py) Then
  ' Nudge: write a breadcrumb so a broken install is diagnosable instead of silent.
  Dim logFile, ts
  logFile = shell.ExpandEnvironmentStrings("%USERPROFILE%") & _
            "\.dsh\xinyuehu-pet-watchdog.log"
  Set ts = CreateObject("Scripting.FileSystemObject").OpenTextFile(logFile, 8, True)
  ts.WriteLine "[launcher] python not found: " & py
  ts.Close
  WScript.Quit 2
End If

' 0 = hidden window, False = do not wait for it to finish
cmd = """" & py & """ """ & watchdog & """"
shell.CurrentDirectory = root
shell.Run cmd, 0, False
