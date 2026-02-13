import os
from datetime import datetime
import subprocess
from pathlib import Path
import shutil

def get_brew_packages(brewfile_path: str):
    try:
        # Get regular brew formulae
        result = subprocess.run(['brew', 'list', '--formula'], capture_output=True, text=True)
        packages = sorted(result.stdout.strip().split('\n')) if result.returncode == 0 and result.stdout.strip() else []

        # Get cask packages (GUI apps installed via Homebrew)
        cask_result = subprocess.run(['brew', 'list', '--cask'], capture_output=True, text=True)
        casks = sorted(cask_result.stdout.strip().split('\n')) if cask_result.returncode == 0 and cask_result.stdout.strip() else []

        # Create Brewfile for reinstallation (write directly to the requested path)
        brewfile_created = False
        dump_result = subprocess.run(
            ['brew', 'bundle', 'dump', '--file', brewfile_path, '--force'],
            capture_output=True,
            text=True
        )
        if dump_result.returncode == 0:
            brewfile_created = True

        return packages, casks, brewfile_created
    except FileNotFoundError:
        print("Homebrew not found. Skipping brew packages.")
        return [], [], False

def get_mas_apps():
    """Return a list of Mac App Store apps via `mas list`.

    Note: When run via launchd, PATH can be minimal, so we try common Homebrew locations.
    """
    try:
        # Try to find `mas` even when PATH is minimal (launchd)
        mas_path = shutil.which(
            'mas',
            path=os.environ.get('PATH', '') + ':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'
        )
        if not mas_path:
            return []

        result = subprocess.run([mas_path, 'list'], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return []

        apps = []
        for line in result.stdout.strip().split('\n'):
            # Format: 497799835 Xcode (15.0)
            parts = line.split(' ', 1)
            if len(parts) == 2:
                apps.append(parts[1].strip())
        return sorted(apps)
    except Exception:
        return []

def get_installed_apps():
    # Define the applications directory path
    apps_dir = "/Applications"
    
    # Get current date for filename
    current_date = datetime.now().strftime("%m-%y")

    # Output folder in Dropbox
    output_dir = Path(os.path.expanduser("~/Library/CloudStorage/Dropbox/Mac Installed Apps"))
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"installed_apps-{current_date}.txt"
    brewfile = output_dir / f"Brewfile-{current_date}"
    
    try:
        # Get .app files
        apps = sorted([item for item in os.listdir(apps_dir) if item.endswith('.app')])
        
        # Get Homebrew packages and Brewfile content
        brew_packages, brew_casks, brewfile_created = get_brew_packages(str(brewfile))
        
        # Get MAS apps
        mas_apps = get_mas_apps()
        
        # Write main report
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"System Report as of {datetime.now().strftime('%B %Y')}\n")
            f.write("=" * 50 + "\n\n")
            
            f.write("Applications (.app)\n")
            f.write("-" * 50 + "\n")
            for app in apps:
                f.write(f"{app}\n")
            
            f.write("\nHomebrew Packages (non-cask)\n")
            f.write("-" * 50 + "\n")
            for package in brew_packages:
                f.write(f"{package}\n")

            f.write("\nHomebrew Casks (GUI Apps via brew)\n")
            f.write("-" * 50 + "\n")
            for cask in brew_casks:
                f.write(f"{cask}\n")

            f.write("\nMac App Store Apps (mas)\n")
            f.write("-" * 50 + "\n")
            if mas_apps:
                for mas_app in mas_apps:
                    f.write(f"{mas_app}\n")
            else:
                f.write("mas not installed, not in PATH for launchd, not signed into App Store, or no MAS apps detected\n")
                f.write("Tip: run `brew install mas` and then `mas list` in Terminal to verify.\n")
            
            if brewfile_created:
                f.write("\nNOTE: A Brewfile has been created in the same folder as this report and can be used to reinstall all Homebrew packages.\n")
                f.write(f"To reinstall using the Brewfile, run: brew bundle install --file \"{brewfile.name}\"\n")
            else:
                f.write("\nNOTE: Brewfile was not created (Homebrew missing or brew bundle dump failed).\n")
                
        print(f"Successfully created {output_file}")
        print(f"Found {len(apps)} applications and {len(brew_packages)} Homebrew packages.")

        # Create reinstall instructions markdown
        readme_file = output_dir / "README-Reinstall.md"
        with open(readme_file, 'w', encoding='utf-8') as r:
            r.write("# Mac Reinstall Instructions\n\n")
            r.write("## 1. Install Homebrew\n")
            r.write("https://brew.sh\n\n")
            r.write("## 2. Restore Applications\n")
            r.write(f"Run from this folder:\n\n``\ncd \"{output_dir}\"\nbrew bundle install --file \"{brewfile.name}\"\n``\n\n")
            r.write("## 3. Mac App Store Apps\n")
            r.write("Install manually or use 'mas list' if you track them separately.\n\n")
            r.write("## 4. Notes\n")
            r.write("This file was auto-generated by app_lister.\n")

        print(f"Created reinstall instructions: {readme_file}")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_installed_apps()