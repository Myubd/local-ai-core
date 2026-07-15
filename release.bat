@echo off
rem Switch the console code page to UTF-8. Without this, echo writes
rem Japanese text using the system default code page (often CP932 on
rem Japanese Windows), but git expects commit messages in UTF-8, which
rem caused mojibake in the commit message written via "git commit -F".
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   local-ai-core Release Tool
echo ========================================
echo.

rem local-ai-core は interview_app / Archlife の両方から git submodule として
rem 参照されている。ここでのリリースは pip パッケージとしてのバージョンを
rem 上げるだけで、他アプリ側の submodule 参照は自動更新されない
rem (このセッションで実際に何度もハマった落とし穴)。そのため、
rem このスクリプトはテストを通してからでないとリリースさせず、
rem 最後に他アプリ側でやるべきことを明示する。

echo [0/4] Running tests...
python -m pytest tests\ -q
if errorlevel 1 (
    echo.
    echo Tests failed. Release cancelled.
    pause
    exit /b 1
)
echo.

set LATEST_TAG=v0.0.0
for /f "tokens=*" %%i in ('git tag --sort=version:refname') do set LATEST_TAG=%%i

echo Current latest tag: %LATEST_TAG%
echo.

set VERSION=%LATEST_TAG:v=%

for /f "tokens=1,2,3 delims=." %%a in ("%VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
    set PATCH=%%c
)

set /a NEXT_MAJOR=%MAJOR%+1
set /a NEXT_MINOR=%MINOR%+1
set /a NEXT_PATCH=%PATCH%+1

set NEW_MAJOR=v%NEXT_MAJOR%.0.0
set NEW_MINOR=v%MAJOR%.%NEXT_MINOR%.0
set NEW_PATCH=v%MAJOR%.%MINOR%.%NEXT_PATCH%

echo Select release type:
echo.
echo   1. Major  (%LATEST_TAG% -^> %NEW_MAJOR%)
echo   2. Minor  (%LATEST_TAG% -^> %NEW_MINOR%)
echo   3. Patch  (%LATEST_TAG% -^> %NEW_PATCH%)
echo   0. Cancel
echo.
set /p CHOICE=Enter number: 

if "%CHOICE%"=="1" set NEW_TAG=%NEW_MAJOR%
if "%CHOICE%"=="2" set NEW_TAG=%NEW_MINOR%
if "%CHOICE%"=="3" set NEW_TAG=%NEW_PATCH%
if "%CHOICE%"=="0" ( echo Cancelled. & pause & exit /b 0 )
if not defined NEW_TAG ( echo Invalid input. & pause & exit /b 1 )

echo.
echo New tag: %NEW_TAG%
echo.
echo NOTE: Type your commit message WITHOUT surrounding quotes.
set /p COMMIT_MSG=Commit message (blank to skip): 

echo.
if not "%COMMIT_MSG%"=="" echo   git add . + git commit
echo   git push origin main
echo   git tag %NEW_TAG%
echo   git push origin %NEW_TAG%
echo.
set /p CONFIRM=Proceed? (y/n): 
if /i not "%CONFIRM%"=="y" ( echo Cancelled. & pause & exit /b 0 )

echo.
if not "%COMMIT_MSG%"=="" (
    rem Write the commit message to a temp file and use "git commit -F" instead
    rem of "git commit -m "%COMMIT_MSG%"". This avoids cmd.exe parser crashes
    rem when the message contains quotes, parentheses, or other special chars
    rem inside this parenthesized if-block.
    set "COMMIT_MSG_FILE=%TEMP%\release_commit_msg_%RANDOM%.txt"
    > "!COMMIT_MSG_FILE!" echo(!COMMIT_MSG!
    echo [1/4] Committing...
    git add .
    git commit -F "!COMMIT_MSG_FILE!"
    del "!COMMIT_MSG_FILE!" >nul 2>&1
) else (
    echo [1/4] Skipping commit.
)

echo [2/4] Pushing main...
git push origin main
if errorlevel 1 ( echo Push failed. & pause & exit /b 1 )

echo [3/4] Creating tag %NEW_TAG%...
git tag %NEW_TAG%
if errorlevel 1 ( echo Tag already exists. & pause & exit /b 1 )

echo [4/4] Pushing tag...
git push origin %NEW_TAG%
if errorlevel 1 ( echo Tag push failed. & pause & exit /b 1 )

echo.
echo ========================================
echo   Released: %NEW_TAG%
echo   https://github.com/Myubd/local-ai-core/actions
echo ========================================
echo.
echo   IMPORTANT: interview_app / Archlife はこの変更を自動では
echo   取り込みません。それぞれのリポジトリで以下を実行してください:
echo.
echo     cd react-fastapi\backend\local_ai_core  (interview_app側)
echo     git pull origin main
echo     cd ..\..\..
echo     git add react-fastapi\backend\local_ai_core
echo     git commit -m "chore: update local_ai_core submodule to %NEW_TAG%"
echo     git push origin main
echo.
echo     cd archlife-fastapi\local_ai_core  (Archlife側)
echo     git pull origin main
echo     cd ..\..
echo     git add archlife-fastapi\local_ai_core
echo     git commit -m "chore: update local_ai_core submodule to %NEW_TAG%"
echo     git push origin main
echo.
pause
