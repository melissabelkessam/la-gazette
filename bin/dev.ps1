# Version Windows PowerShell de bin/dev : lance Postgres, Prefect et une collecte.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose up --build @args
