; KB-Assistant standalone NSIS installer.
; Rebuilt from the existing release binary + backend resources using the NSIS
; toolchain cached at src-tauri/target/.tauri/NSIS (no MSVC required).
; Uninstall logic lives in ../windows/uninstall-cleanup.ps1.

Unicode true
!include "LogicLib.nsh"

!define PRODUCT_NAME "KB-Assistant"
!define VERSION "1.0.0"
!define PUBLISHER "Ningo1077"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\KB-Assistant"

Name "${PRODUCT_NAME} ${VERSION}"
Caption "AI 知识库问答助手 ${VERSION} 安装程序"
OutFile "..\target\release\bundle\nsis\KB-Assistant_${VERSION}_x64-setup.exe"
InstallDir "$LOCALAPPDATA\KB-Assistant"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Icon "..\icons\icon.ico"
UninstallIcon "..\icons\icon.ico"
ShowInstDetails show
ShowUninstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  ; Close a running instance before replacing files.
  nsExec::ExecToLog 'taskkill /F /IM kb-assistant.exe /T'
  Pop $0

  SetOutPath "$INSTDIR"
  File "..\target\release\kb-assistant.exe"
  File "..\windows\uninstall-cleanup.ps1"
  File "..\icons\icon.ico"

  ; Explicit allow-list: never ship .env, data/, uploads/ or *.bak from the dev machine.
  ; data/ is recreated on first launch; the DB here is a clean empty seed.
  SetOutPath "$INSTDIR\backend"
  File "..\..\backend\requirements.txt"
  File "..\..\backend\.env.example"

  SetOutPath "$INSTDIR\backend\app"
  File /r /x "__pycache__" /x "*.pyc" "..\..\backend\app\*.*"

  SetOutPath "$INSTDIR\backend\scripts"
  File /r /x "__pycache__" /x "*.pyc" "..\..\backend\scripts\*.*"

  SetOutPath "$INSTDIR\backend\.venv"
  File /r /x "__pycache__" /x "*.pyc" /x "*.log" "..\..\backend\.venv\*.*"

  SetOutPath "$INSTDIR\backend\data"
  File "seed\app.db"

  ; Start Menu + desktop shortcuts (including an explicit uninstall entry).
  CreateDirectory "$SMPROGRAMS\KB-Assistant"
  CreateShortcut "$SMPROGRAMS\KB-Assistant\KB-Assistant.lnk" "$INSTDIR\kb-assistant.exe" "" "$INSTDIR\icon.ico"
  CreateShortcut "$SMPROGRAMS\KB-Assistant\Uninstall KB-Assistant.lnk" "$INSTDIR\uninstall.exe"
  IfSilent _kb_skip_desktop
  CreateShortcut "$DESKTOP\AI 知识库问答助手.lnk" "$INSTDIR\kb-assistant.exe" "" "$INSTDIR\icon.ico"
  _kb_skip_desktop:

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; "Add or remove programs" entry (current user, no admin rights needed).
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\kb-assistant.exe"
SectionEnd

Section "Uninstall"
  ; Ask whether to keep the knowledge base. Silent uninstall defaults to KEEP.
  StrCpy $R0 "-KeepData"
  IfSilent _kb_un_run
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 \
    "是否保留知识库数据（文档、数据库、上传文件）？$\r$\n$\r$\n是 = 卸载前备份到 文档\KB-Assistant-Backup$\r$\n否 = 连同程序一起删除" \
    IDYES _kb_un_keep IDNO _kb_un_drop
  _kb_un_keep:
    StrCpy $R0 "-KeepData"
    Goto _kb_un_run
  _kb_un_drop:
    StrCpy $R0 ""
  _kb_un_run:
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\uninstall-cleanup.ps1" -InstallDir "$INSTDIR" $R0'
    Pop $0

  Delete "$SMPROGRAMS\KB-Assistant\KB-Assistant.lnk"
  Delete "$SMPROGRAMS\KB-Assistant\Uninstall KB-Assistant.lnk"
  RMDir "$SMPROGRAMS\KB-Assistant"
  Delete "$DESKTOP\AI 知识库问答助手.lnk"

  DeleteRegKey HKCU "${UNINST_KEY}"

  ; Remove the whole install tree. NSIS defers deleting the running uninstall.exe.
  RMDir /r "$INSTDIR"

  IfFileExists "$DOCUMENTS\KB-Assistant-Backup\LATEST.txt" 0 _kb_un_done
    DetailPrint "知识库数据已备份到 文档\KB-Assistant-Backup"
  _kb_un_done:
SectionEnd
