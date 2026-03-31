@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "WEB_DIR=%ROOT_DIR%apps\web"
set "WORKSPACE_NAME=glass-box-web"
set "PNPM_COMMAND=pnpm"

if not exist "%WEB_DIR%\package.json" (
  echo [run-frontend] Missing package file: "%WEB_DIR%\package.json"
  exit /b 1
)

where pnpm >nul 2>nul
if errorlevel 1 (
  where corepack >nul 2>nul
  if not errorlevel 1 (
    set "PNPM_COMMAND=corepack pnpm"
    echo [run-frontend] pnpm not found. Falling back to corepack pnpm.
  ) else (
    where npx >nul 2>nul
    if not errorlevel 1 (
      set "PNPM_COMMAND=npx --yes pnpm"
      echo [run-frontend] pnpm/corepack not found. Falling back to npx pnpm.
    ) else (
      where npm >nul 2>nul
      if not errorlevel 1 (
        set "PNPM_COMMAND=npm exec --yes pnpm"
        echo [run-frontend] pnpm/corepack/npx not found. Falling back to npm exec pnpm.
      ) else (
        echo [run-frontend] pnpm, corepack, npx, and npm are not available in PATH.
        exit /b 1
      )
    )
  )
)

set "INSTALL_COMMAND=%PNPM_COMMAND% install --frozen-lockfile"
set "BUILD_COMMAND=%PNPM_COMMAND% --filter %WORKSPACE_NAME% run build"
set "START_COMMAND=%PNPM_COMMAND% --filter %WORKSPACE_NAME% run start"

pushd "%ROOT_DIR%"

if not exist "%ROOT_DIR%pnpm-lock.yaml" (
  set "INSTALL_COMMAND=%PNPM_COMMAND% install"
)

echo [run-frontend] Syncing Node dependencies...
call %INSTALL_COMMAND%
if errorlevel 1 goto :end

echo [run-frontend] Building latest frontend bundle...
call %BUILD_COMMAND%
if errorlevel 1 goto :end

if /I "%NO_START%"=="1" (
  echo [run-frontend] Build completed. Skipping Next.js start because NO_START=1.
  set "EXIT_CODE=0"
  goto :finish
)

echo [run-frontend] Starting Next.js production server...
call %START_COMMAND%

:end
set "EXIT_CODE=%ERRORLEVEL%"

:finish
popd
exit /b %EXIT_CODE%