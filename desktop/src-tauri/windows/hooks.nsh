; Installer hooks: offer to put the frozen reframe CLI ($INSTDIR\sidecar) on the user's PATH,
; and take it off again at uninstall.
;
; PowerShell edits the registry value: NSIS strings are NSIS_MAX_STRLEN long, so a longer PATH
; read with ReadRegStr would come back empty or cut, and writing it back would lose it. The
; value stays REG_EXPAND_SZ with its %VARIABLES% unexpanded.

!include "WinMessages.nsh"

!define REFRAME_PATH_READ "$$k = Get-Item 'HKCU:\Environment'; $$d = $$env:REFRAME_CLI_DIR; $$parts = @($$k.GetValue('Path', '', 'DoNotExpandEnvironmentNames') -split ';' | Where-Object { $$_ })"
!define REFRAME_PATH_WRITE "[Microsoft.Win32.Registry]::SetValue('HKEY_CURRENT_USER\Environment', 'Path', ($$new -join ';'), 'ExpandString')"

!macro REFRAME_EDIT_PATH SCRIPT
  System::Call 'Kernel32::SetEnvironmentVariable(t "REFRAME_CLI_DIR", t "$INSTDIR\sidecar") i'
  nsExec::ExecToLog `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "${REFRAME_PATH_READ}; ${SCRIPT}"`
  Pop $0
  SendMessage ${HWND_BROADCAST} ${WM_SETTINGCHANGE} 0 "STR:Environment" /TIMEOUT=5000
!macroend

!macro NSIS_HOOK_POSTINSTALL
  IfSilent reframe_path_done
  MessageBox MB_YESNO|MB_ICONQUESTION "Add the reframe command-line tool to your PATH?$\r$\n$\r$\n$INSTDIR\sidecar" /SD IDNO IDNO reframe_path_done
  !insertmacro REFRAME_EDIT_PATH "if ($$parts -notcontains $$d) { $$new = $$parts + $$d; ${REFRAME_PATH_WRITE} }"
  reframe_path_done:
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  !insertmacro REFRAME_EDIT_PATH "$$new = @($$parts | Where-Object { $$_ -ne $$d }); if ($$new.Count -ne $$parts.Count) { ${REFRAME_PATH_WRITE} }"
!macroend
