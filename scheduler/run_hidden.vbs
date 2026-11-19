' Runs run_followups.bat with no window (called by the Task Scheduler).
' Same pattern as job-fit-screener: a visible console could be closed by
' accident and kill the run halfway.
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = folder
' 0 = hidden window; True = wait until it finishes
WScript.Quit shell.Run("cmd /c """ & folder & "\run_followups.bat""", 0, True)
