# CPLDD
Deployment script, written in python,  for Qt or Non Qt-C/C++ executable programs, which essentially scans and copies all "dll" dependencies into a single folder along with the executable itself. cpldd utilizes the console output of ldd.exe from msys2 project. In general, the script can be utilized to deploy executables irrespective of the compiler toolchain (MSVC/MSYS2/Mingw/Cygwin) used to build the executable itself. It is assumed that the shell/cmd environment in which the cpld is run, has all the dependencies in its path. If not so, only partial dependencies will be copied.

#Command line usage:

python cpldd.py Input_Exe_Path Output_Folder_Path

cpldd.exe Input_Exe_Path Output_Folder_Path


  ![MSVC output](screenshot_msvc.PNG)
  ![MSVC output](screenshot_msys2.PNG)

#Optional Arguments:

-f : Force dependencies from "system32" folder to be copied to the deployment folder
