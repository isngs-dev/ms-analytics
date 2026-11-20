# Copies the local database dump (backups\ms.dump) into the Render database.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File scripts\push_db_to_render.ps1
# Before: suspend the ms-api service on Render. After: resume it.
$ErrorActionPreference = "Stop"
$dump = Join-Path (Split-Path $PSScriptRoot -Parent) "backups"
if (-not (Test-Path (Join-Path $dump "ms.dump"))) { throw "backups\ms.dump not found" }

$secure = Read-Host "Paste the External Database URL from Render (typing stays hidden), then press Enter" -AsSecureString
$url = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if ($url -notmatch '^postgres(ql)?://') { throw "That is not a postgres:// URL" }
if ($url -notmatch '\.render\.com') { throw "This looks like the INTERNAL URL (no .render.com in the host). Use the External Database URL." }

Write-Host "`n1/3 Restoring the dump into the Render database (a few minutes)..." -ForegroundColor Cyan
docker run --rm -v "${dump}:/b" postgres:16-alpine pg_restore --clean --if-exists --no-owner --no-privileges -d $url /b/ms.dump
Write-Host "(warnings above about 'does not exist' are normal on the first restore)" -ForegroundColor DarkGray

Write-Host "`n2/3 Clearing stuck 'running' sync rows..." -ForegroundColor Cyan
docker run --rm postgres:16-alpine psql $url -c "update sync_log set status='failed', finished_at=now(), error_text='stopped before restore' where status='running';"

Write-Host "`n3/3 Checking what is in the Render database now..." -ForegroundColor Cyan
docker run --rm postgres:16-alpine psql $url -c "select count(*) as live_forms from forms where deleted_at is null;" -c "select count(*) as files from src_file where status='active';"

Write-Host "`nDone. Now resume ms-api on Render." -ForegroundColor Green
