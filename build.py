"""
Build SpriteStack Studio into a standalone .exe and create a desktop shortcut.

Usage:
    python build.py

This will:
1. Package the app into a single-folder exe using PyInstaller
2. Create a desktop shortcut pointing to the exe
"""

import subprocess
import sys
import os


def install_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
        print("[OK] PyInstaller already installed.")
    except ImportError:
        print("[...] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller installed.")


def build_exe():
    """Run PyInstaller to create the exe."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_py = os.path.join(script_dir, "main.py")

    icon_path = os.path.join(script_dir, "sprites_stack.ico")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "SpriteStackStudio",
        "--windowed",               # No console window
        "--noconfirm",              # Overwrite without asking
        "--clean",                  # Clean build cache
        "--add-data", f"{os.path.join(script_dir, 'app')};app",
        f"--icon={icon_path}",
        main_py,
    ]

    print("[...] Building exe with PyInstaller (this may take a minute)...")
    subprocess.check_call(cmd, cwd=script_dir)
    print("[OK] Build complete.")

    exe_path = os.path.join(script_dir, "dist", "SpriteStackStudio", "SpriteStackStudio.exe")
    if os.path.exists(exe_path):
        print(f"[OK] Exe located at: {exe_path}")
    else:
        print("[!!] Exe not found at expected path. Check dist/ folder.")
    return exe_path


def create_desktop_shortcut(exe_path):
    """Create a Windows desktop shortcut (.lnk) using PowerShell COM."""
    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    shortcut_path = os.path.join(desktop, "SpriteStack Studio.lnk")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(script_dir, "sprites_stack.ico")
    working_dir = os.path.dirname(exe_path)

    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{exe_path}"
$Shortcut.WorkingDirectory = "{working_dir}"
$Shortcut.Description = "SpriteStack Studio - Sprite Stacking and Pixel Art Editor"
$Shortcut.IconLocation = "{icon_path},0"
$Shortcut.Save()
'''

    print("[...] Creating desktop shortcut...")
    result = subprocess.run(
        ["powershell", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[OK] Desktop shortcut created: {shortcut_path}")
    else:
        print(f"[!!] Failed to create shortcut: {result.stderr}")


def create_shortcut_without_build():
    """Create a shortcut that runs the Python script directly (no exe build needed)."""
    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    shortcut_path = os.path.join(desktop, "SpriteStack Studio.lnk")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_py = os.path.join(script_dir, "main.py")
    python_exe = sys.executable

    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{python_exe}"
$Shortcut.Arguments = '"{main_py}"'
$Shortcut.WorkingDirectory = "{script_dir}"
$Shortcut.Description = "SpriteStack Studio - Sprite Stacking and Pixel Art Editor"
$Shortcut.WindowStyle = 1
$Shortcut.Save()
'''

    print("[...] Creating desktop shortcut (Python launcher)...")
    result = subprocess.run(
        ["powershell", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[OK] Desktop shortcut created: {shortcut_path}")
    else:
        print(f"[!!] Failed to create shortcut: {result.stderr}")


if __name__ == "__main__":
    print("=" * 50)
    print("  SpriteStack Studio - Build & Shortcut Tool")
    print("=" * 50)
    print()
    print("Options:")
    print("  1) Full build (exe + desktop shortcut)")
    print("  2) Quick shortcut only (launches via Python)")
    print()

    choice = input("Choose option [1/2]: ").strip()

    if choice == "1":
        install_pyinstaller()
        exe_path = build_exe()
        if os.path.exists(exe_path):
            create_desktop_shortcut(exe_path)
        print("\nDone! You can now launch SpriteStack Studio from your desktop.")
    elif choice == "2":
        create_shortcut_without_build()
        print("\nDone! Desktop shortcut created (requires Python to be installed).")
    else:
        print("Invalid option. Run again and choose 1 or 2.")
