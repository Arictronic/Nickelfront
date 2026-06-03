@echo off
set "NF_ROOT=%~dp0..\.."
if not exist "%NF_ROOT%\scripts\load_env.bat" exit /b 1
call "%NF_ROOT%\scripts\load_env.bat" %*
exit /b %ERRORLEVEL%
