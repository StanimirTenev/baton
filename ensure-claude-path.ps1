# Ensure Claude Code's install dir (~\.local\bin) is on the persisted USER PATH.
# The native Windows installer does not always add it, which leaves `claude` "not found"
# in every new terminal. User scope, no administrator. Safe to run repeatedly.
$bin = Join-Path $env:USERPROFILE ".local\bin"
$p = [Environment]::GetEnvironmentVariable("Path", "User")
if ($p -and ($p.Split(';') -contains $bin)) {
    Write-Host "PATH: '$bin' already present."
} else {
    if ([string]::IsNullOrEmpty($p)) { $np = $bin } else { $np = "$p;$bin" }
    [Environment]::SetEnvironmentVariable("Path", $np, "User")
    Write-Host "PATH: added '$bin' to the user PATH. Log out/in (or open a new terminal after that) to use 'claude'."
}
