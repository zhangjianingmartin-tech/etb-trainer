@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw etb_overlay.py) || (start "" pyw -3 etb_overlay.py)
