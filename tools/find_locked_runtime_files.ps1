param(
    [string]$ProjectRoot = (Resolve-Path ".").Path
)

Write-Host "HyperSmart runtime file diagnostic"
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host ""
Write-Host "Runtime SQLite files:"
Get-ChildItem -Path $ProjectRoot -Recurse -File -Include *.sqlite3,*.sqlite3-wal,*.sqlite3-shm,*.db,*.db-wal,*.db-shm -ErrorAction SilentlyContinue |
    Select-Object FullName, Length, LastWriteTime |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Suspect local processes (not killed automatically):"
Get-Process | Where-Object {
    $_.ProcessName -match "python|uvicorn|fastapi|sqlite|hl_observer|hyper_smart|powershell|cmd|node|chrome" -or
    $_.MainWindowTitle -match "Projet invest|hl_observer|hyper_smart|HyperSmart"
} | Select-Object Id, ProcessName, MainWindowTitle | Format-Table -AutoSize

Write-Host ""
Write-Host "Sysinternals Handle check:"
$handle = Get-Command handle.exe -ErrorAction SilentlyContinue
if ($handle) {
    Write-Host "handle.exe found. Suggested read-only command:"
    Write-Host "  handle.exe hl_observer.sqlite3"
} else {
    Write-Host "handle.exe not found. Optional: install Sysinternals Handle to identify exact locking process."
}
Write-Host ""
Write-Host "Safe action: stop the local dashboard/process using the DB, then archive with tools/create_clean_archive.ps1."
