@ECHO OFF
set "pycommand=py -3"
set "op_file=%~dp0zconfig/NSCB_options.cmd"
call :program_logo
setlocal
if exist "%op_file%" call "%op_file%" 	  
endlocal & ( 
set "pycommand=%pycommand%"
)

ECHO.
ECHO Installing dependencies 
ECHO.
%pycommand% -m pip install urllib3 unidecode tqdm bs4 tqdm requests image pywin32 pycryptodome pykakasi
ECHO.
ECHO **********************************************************************************
ECHO ---IMPORTANT: Check if dependencies were installed correctly before continuing---
ECHO **********************************************************************************
ECHO.
PAUSE
exit /B

:program_logo

ECHO                                        __          _ __    __         
ECHO                  ____  _____ ____     / /_  __  __(_) /___/ /__  _____
ECHO                 / __ \/ ___/ ___/    / __ \/ / / / / / __  / _ \/ ___/
ECHO                / / / (__  ) /__     / /_/ / /_/ / / / /_/ /  __/ /    
ECHO               /_/ /_/____/\___/____/_.___/\__,_/_/_/\__,_/\___/_/     
ECHO                              /_____/                                  
ECHO -------------------------------------------------------------------------------------
ECHO                         NINTENDO SWITCH CLEANER AND BUILDER
ECHO                      (THE XCI MULTI CONTENT BUILDER AND MORE)
ECHO -------------------------------------------------------------------------------------
ECHO =============================     BY JULESONTHEROAD     =============================
ECHO -------------------------------------------------------------------------------------
exit /B