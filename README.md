# CPLDD
<div style="text-align: justify">Deployment script, written in python,  for Qt or Non Qt-C/C++ executable programs, which essentially scans and copies all "dll"dependencies into a single folder along with the executable itself. CPLDD utilizes the console output of ldd.exe from msys2 project. In general, the script can be utilized to deploy executables irrespective of the compiler toolchain(MSVC/MSYS2/Mingw/Cygwin) used to build the executable itself. It is assumed that the shell/cmd environment in which the cpld is run, has all the dependencies in its path. If not so, only partial dependencies will be copied.</div>

## Command line usage:

***python cpldd.py <Input_Exe_File> <Output_Folder_Path>***

***cpldd.exe <Input_Exe_File> <Output_Folder_Path>***

### Optional Arguments:

-f : Force dependencies from "system32" folder to be copied to the deployment folder

## Sample Output:
The following two screenshots show console outputs when a C++ executable which is an oucome of very complicated project with tons of dependencies (Qt//VTK/ITK/OpenBlas/ ...) is deployed using cpld. The two screenshots only differ by the compiler tool chain (MSVC vs MSYS2), which can be seen in the following images.
  ![MSVC output](screenshot_msvc.PNG)
  ![MSYS2 output](screenshot_msys2.PNG)

Despite all the complicated dependencies, CPLDD has been shown to be successful 100%. 
