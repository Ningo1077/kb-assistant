; KB-Assistant NSIS installer hooks for the standard `tauri build` pipeline.
; Referenced from tauri.conf.json > bundle > windows > nsis > installerHooks.
; The standalone NSIS installer (nsis/setup.nsi) implements the same logic.

!macro NSIS_HOOK_PREINSTALL
  ; Close a running instance before an upgrade so files are not locked.
  nsExec::ExecToLog 'taskkill /F /IM kb-assistant.exe /T'
  Pop $0
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Explicit uninstall entry in the Start Menu.
  CreateDirectory "$SMPROGRAMS\KB-Assistant"
  CreateShortcut "$SMPROGRAMS\KB-Assistant\Uninstall KB-Assistant.lnk" "$INSTDIR\uninstall.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Stop processes, then (optionally) back up the knowledge base.
  StrCpy $R0 ""
  IfSilent _kb_hook_keep
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 \
    "Keep your knowledge base data (documents, database, uploads)?$\r$\n$\r$\nYES = back up to Documents\KB-Assistant-Backup before uninstalling.$\r$\nNO  = delete all data together with the app." \
    IDYES _kb_hook_keep IDNO _kb_hook_run
  _kb_hook_keep:
    StrCpy $R0 "-KeepData"
  _kb_hook_run:
    ; Tauri may place the helper at the install root or under resources/.
    IfFileExists "$INSTDIR\uninstall-cleanup.ps1" 0 _kb_hook_try_resources
      nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\uninstall-cleanup.ps1" -InstallDir "$INSTDIR" $R0'
      Pop $0
      Goto _kb_hook_done
    _kb_hook_try_resources:
    IfFileExists "$INSTDIR\resources\uninstall-cleanup.ps1" 0 _kb_hook_missing
      nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\resources\uninstall-cleanup.ps1" -InstallDir "$INSTDIR" $R0'
      Pop $0
      Goto _kb_hook_done
    _kb_hook_missing:
      DetailPrint "uninstall-cleanup.ps1 not found - skipping process cleanup"
    _kb_hook_done:
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  IfFileExists "$DOCUMENTS\KB-Assistant-Backup\LATEST.txt" 0 _kb_hook_post_done
    DetailPrint "Knowledge base backup: $DOCUMENTS\KB-Assistant-Backup"
  _kb_hook_post_done:
!macroend
