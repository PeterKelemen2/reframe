; Installer hooks: the per-user programs folder, the file associations' earlier classes, the
; offer to put the frozen reframe CLI ($INSTDIR\sidecar) on the user's PATH, and Reframe's own
; data at uninstall.

!include "LogicLib.nsh"
!include "WinMessages.nsh"

; Tauri's per-user default, %LOCALAPPDATA%\Reframe, is Reframe's data folder: the installer's
; tools\ffmpeg\bin would be the files that "Use bundled FFmpeg" downloads there, and the
; uninstaller would delete them. The program goes to the per-user programs folder instead, both
; on the directory page (GUI init) and in a silent install (the section).
!define MUI_CUSTOMFUNCTION_GUIINIT ReframeProgramDir
!macro REFRAME_PROGRAM_DIR
  ${If} $INSTDIR == "$LOCALAPPDATA\Reframe"
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Reframe"
  ${EndIf}
!macroend
Function ReframeProgramDir
  !insertmacro REFRAME_PROGRAM_DIR
FunctionEnd

; Each extension of bundle.fileAssociations with its class name.
!macro REFRAME_FILE_CLASSES MACRO
  !insertmacro ${MACRO} "mkv" "Reframe.mkv"
  !insertmacro ${MACRO} "mp4" "Reframe.mp4"
  !insertmacro ${MACRO} "m2ts" "Reframe.m2ts"
  !insertmacro ${MACRO} "ts" "Reframe.m2ts"
  !insertmacro ${MACRO} "avi" "Reframe.avi"
  !insertmacro ${MACRO} "mov" "Reframe.mov"
  !insertmacro ${MACRO} "webm" "Reframe.webm"
!macroend

; Tauri's association saves the extension's class as <class>_backup and the uninstaller puts it
; back. Installed over itself (an update, a reinstall) it would save Reframe's own class, and the
; uninstall would leave the extension on a class it deleted: the earlier class is restored first.
!macro REFRAME_RESTORE_EARLIER_CLASS EXT CLASS
  ReadRegStr $R0 SHCTX "Software\Classes\.${EXT}" ""
  ${If} $R0 == "${CLASS}"
    ReadRegStr $R0 SHCTX "Software\Classes\.${EXT}" "${CLASS}_backup"
    WriteRegStr SHCTX "Software\Classes\.${EXT}" "" "$R0"
  ${EndIf}
!macroend

; After Tauri's uninstall has put the earlier class back: the saved copy, an empty class and an
; extension key that had nothing else go.
!macro REFRAME_DROP_SAVED_CLASS EXT CLASS
  DeleteRegValue SHCTX "Software\Classes\.${EXT}" "${CLASS}_backup"
  ReadRegStr $R0 SHCTX "Software\Classes\.${EXT}" ""
  ${If} $R0 == ""
    DeleteRegValue SHCTX "Software\Classes\.${EXT}" ""
  ${EndIf}
  DeleteRegKey /ifempty SHCTX "Software\Classes\.${EXT}"
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro REFRAME_PROGRAM_DIR
  SetOutPath $INSTDIR
  !insertmacro REFRAME_FILE_CLASSES REFRAME_RESTORE_EARLIER_CLASS
!macroend

; PowerShell edits the PATH: NSIS strings are NSIS_MAX_STRLEN long, so a longer PATH read with
; ReadRegStr would come back empty or cut, and writing it back would lose it. The value stays
; REG_EXPAND_SZ with its %VARIABLES% unexpanded.

!define REFRAME_PATH_READ "$$k = Get-Item 'HKCU:\Environment'; $$d = $$env:REFRAME_CLI_DIR; $$parts = @($$k.GetValue('Path', '', 'DoNotExpandEnvironmentNames') -split ';' | Where-Object { $$_ })"
!define REFRAME_PATH_WRITE "[Microsoft.Win32.Registry]::SetValue('HKEY_CURRENT_USER\Environment', 'Path', ($$new -join ';'), 'ExpandString')"

!macro REFRAME_EDIT_PATH SCRIPT
  System::Call 'Kernel32::SetEnvironmentVariable(t "REFRAME_CLI_DIR", t "$INSTDIR\sidecar") i'
  nsExec::ExecToLog `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "${REFRAME_PATH_READ}; ${SCRIPT}"`
  Pop $0
  SendMessage ${HWND_BROADCAST} ${WM_SETTINGCHANGE} 0 "STR:Environment" /TIMEOUT=5000
!macroend

; The updater installs over the old version in place (passive, /UPDATE): the folder and the
; user's earlier answer stay, so nothing is asked and the entry is left as it is.
!macro NSIS_HOOK_POSTINSTALL
  ${IfNot} ${Silent}
  ${AndIf} $PassiveMode <> 1
  ${AndIf} $UpdateMode <> 1
    MessageBox MB_YESNO|MB_ICONQUESTION "Add the reframe command-line tool to your PATH?$\r$\n$\r$\n$INSTDIR\sidecar" IDNO reframe_path_done
    !insertmacro REFRAME_EDIT_PATH "if ($$parts -notcontains $$d) { $$new = $$parts + $$d; ${REFRAME_PATH_WRITE} }"
    reframe_path_done:
  ${EndIf}
!macroend

; "Delete the application data" also removes Reframe's own folder (the queue, settings,
; presets, logs, cache and fetched tools), which is not named after the bundle identifier.
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
    !insertmacro REFRAME_FILE_CLASSES REFRAME_DROP_SAVED_CLASS
    !insertmacro REFRAME_EDIT_PATH "$$new = @($$parts | Where-Object { $$_ -ne $$d }); if ($$new.Count -ne $$parts.Count) { ${REFRAME_PATH_WRITE} }"
    ${If} $DeleteAppDataCheckboxState = 1
      SetShellVarContext current
      RmDir /r "$LOCALAPPDATA\Reframe"
    ${EndIf}
  ${EndIf}
!macroend
