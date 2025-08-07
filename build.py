import os
import sys
import subprocess
import shutil
from pathlib import Path

def main():
    # Get the project root directory
    project_root = Path(__file__).parent
    src_dir = project_root / "src"
    build_dir = project_root / "build"
    dist_dir = project_root / "dist"
    
    # Create build command
    main_script = src_dir / "MSCPlaylistConverter.py"
    icon_path = src_dir / "resources" / "icon.ico"
    
    pyinstaller_cmd = [
        "pyinstaller",
        "--onefile",                    # Create a single executable file
        "--windowed",                   # Hide console window (GUI app)
        "--name=MSCPlaylistConverter",  # Name of the executable
        f"--icon={icon_path}",         # Application icon
        "--add-data", f"{src_dir / 'resources'};resources",  # Include resources folder
        "--add-data", f"{src_dir / 'resources' / 'ffmpeg'};ffmpeg",  # Include ffmpeg folder specifically
        "--add-data", f"{icon_path};.",                      # Include icon file in root
        "--hidden-import=PIL._tkinter_finder",               # Ensure PIL works
        "--collect-all=yt_dlp",                              # Include all yt-dlp dependencies
        "--exclude-module=tkinter.test",                     # Exclude test modules
        "--exclude-module=test",                             # Exclude test modules
        "--exclude-module=unittest",                         # Exclude unittest
        "--uac-admin",                                       # Request admin rights (helps with AV)
        "--version-file=version_info.txt",                   # Add version info (if exists)
        "--clean",                                           # Clean PyInstaller cache
        str(main_script)
    ]
    
    print("Building executable with PyInstaller...")
    print(f"Command: {' '.join(pyinstaller_cmd)}")
    
    try:
        # Run PyInstaller
        result = subprocess.run(pyinstaller_cmd, check=True, cwd=project_root)
        
        # Move the executable to the build directory
        exe_source = dist_dir / "MSCPlaylistConverter.exe"
        exe_dest = build_dir / "MSCPlaylistConverter.exe"
        
        if exe_source.exists():
            build_dir.mkdir(exist_ok=True)
            shutil.move(str(exe_source), str(exe_dest))
            print(f"Executable created successfully: {exe_dest}")
            print(f"File size: {exe_dest.stat().st_size / 1024 / 1024:.1f} MB")
        else:
            print("Executable not found in dist directory")
            return False
            
        # Clean up temporary files
        print("Cleaning up temporary files...")
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        
        # Remove spec file
        spec_file = project_root / "MSCPlaylistConverter.spec"
        if spec_file.exists():
            spec_file.unlink()
        
        # Clean up PyInstaller build artifacts (keep only the executable)
        pyinstaller_build_dir = build_dir / "MSCPlaylistConverter"
        if pyinstaller_build_dir.exists():
            print("Removing PyInstaller build artifacts...")
            shutil.rmtree(pyinstaller_build_dir)

        print("Build completed successfully!")
        print(f"Executable location: {exe_dest}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error code {e.returncode}")
        return False
    except Exception as e:
        print(f"Build failed with error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
