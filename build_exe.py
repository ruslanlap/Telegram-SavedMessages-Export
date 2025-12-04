"""
Build script for creating Windows executable

Requirements:
    pip install pyinstaller

Usage:
    python build_exe.py
"""

import subprocess
import sys
import os


def build():
    """Build Windows executable"""
    
    # Determine path separator for --add-data (Windows uses ;, Linux/Mac uses :)
    sep = ";" if sys.platform == "win32" else ":"
    
    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=TelegramNotionExporter",
        "--onefile",                    # Single executable
        "--windowed",                   # No console window
        "--icon=icon.ico",              # Icon (optional)
        f"--add-data=README.md{sep}.",  # Include README
        "--hidden-import=pyrogram",
        "--hidden-import=notion_client",
        "--hidden-import=PyQt6",
        "--clean",                      # Clean cache
        "telegram_notion_gui.py"
    ]
    
    # Remove icon option if no icon file
    if not os.path.exists("icon.ico"):
        cmd.remove("--icon=icon.ico")
    
    # Remove README option if no README
    if not os.path.exists("README.md"):
        cmd.remove(f"--add-data=README.md{sep}.")
    
    print("=" * 50)
    print("Building Telegram Notion Exporter")
    print("=" * 50)
    print()
    print("🔨 Building TelegramNotionExporter.exe...")
    print(f"Command: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd)
    
    print()
    print("=" * 50)
    if result.returncode == 0:
        print("✅ Build successful!")
        print()
        print("📁 Executable: dist/TelegramNotionExporter.exe")
        print()
        print("📋 Usage:")
        print("   1. Run TelegramNotionExporter.exe")
        print("   2. Enter credentials in Credentials tab")
        print("   3. Click Start Export - dialogs will ask for code/password")
    else:
        print("❌ Build failed!")
        sys.exit(1)


if __name__ == "__main__":
    build()
