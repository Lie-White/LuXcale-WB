@echo off
rem Runs this project's own uv with everything kept inside C:\Imaging\tools:
rem Python installs, the package cache and any Python executables. Only uv-managed Python is used.
set "UV_PYTHON_INSTALL_DIR=%~dp0python"
set "UV_CACHE_DIR=%~dp0uv-cache"
set "UV_PYTHON_BIN_DIR=%~dp0bin"
set "UV_PYTHON_PREFERENCE=only-managed"
rem matplotlib's font cache and settings, which otherwise go to %LOCALAPPDATA%\matplotlib.
set "MPLCONFIGDIR=%~dp0mplconfig"
rem napari and other platformdirs users: caches and settings inside the project.
set "WIN_PD_OVERRIDE_LOCAL_APPDATA=%~dp0appdata\Local"
set "WIN_PD_OVERRIDE_APPDATA=%~dp0appdata\Roaming"
set "NAPARI_CONFIG=%~dp0appdata\napari\settings.yaml"
set "QT_API=pyside6"
set "QT_DISABLE_SHADER_DISK_CACHE=1"
"%~dp0uv\uv.exe" %*
