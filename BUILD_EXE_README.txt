ATR-1000 / TCI Protection Monitor - Windows EXE Build

1. Put these two files in the SAME folder:
   - atr1000_tci_protection_monitor_v6_no_login.py
   - BUILD_EXE.bat

2. Double-click BUILD_EXE.bat.

3. The first build may take a few minutes because it installs:
   - PyInstaller
   - websocket-client

4. When complete, your application will be:
   dist\ATR1000_Protection_Monitor.exe

5. You can copy that EXE somewhere else and run it without starting Python manually.

Notes:
- Build the EXE on Windows. PyInstaller packages for the operating system it is running on.
- Windows SmartScreen may warn about a self-built unsigned application.
- Windows Firewall may ask for permission the first time the built-in web server is started.
  Allow access only on the private/internal network you intend to use.
