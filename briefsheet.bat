@echo off
rem Command-line use:  briefsheet.bat FLIGHTPLAN.pdf [--gate 13 --pax 2/11 --pax 15/144]
rem Run with no arguments to open the window.
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
py -m briefsheet %*
