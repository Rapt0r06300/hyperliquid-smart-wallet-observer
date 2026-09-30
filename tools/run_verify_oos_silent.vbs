Option Explicit

Dim fileSystem, projectRoot, shell, command, exitCode

Set fileSystem = CreateObject("Scripting.FileSystemObject")
projectRoot = fileSystem.GetParentFolderName(fileSystem.GetParentFolderName(WScript.ScriptFullName))

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = projectRoot

command = """" & projectRoot & "\LANCER_HYPERSMART.cmd"" verify-oos run"
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
