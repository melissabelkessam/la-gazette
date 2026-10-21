# Version Windows PowerShell de bin/test : lint (ruff) puis tests (pytest) dans un conteneur.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker run --rm -v "${PWD}:/app" -w /app python:3.13-slim `
  sh -c "pip install --quiet --no-cache-dir -r requirements-dev.txt && ruff check . && pytest"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
