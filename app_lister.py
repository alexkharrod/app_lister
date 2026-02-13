import os
from datetime import datetime
import subprocess
from pathlib import Path
import shutil
import sys

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

def safe_copy_file(src: Path, dest_dir: Path) -> bool:
    """Copy a single file into dest_dir. Returns True if copied."""
    try:
        if src.exists() and src.is_file():
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_dir / src.name)
            return True
    except Exception:
        pass
    return False


def safe_copy_dir(src: Path, dest_dir: Path) -> bool:
    """Copy a directory into dest_dir/<src.name>. Returns True if copied."""
    try:
        if src.exists() and src.is_dir():
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / src.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            return True
    except Exception:
        pass
    return False


def run_cmd_to_file(cmd: list[str], outfile: Path) -> bool:
    """Run a command and write stdout to outfile. Returns True on success."""
    try:
        outfile.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return False
        with open(outfile, 'w', encoding='utf-8') as f:
            f.write(result.stdout)
        return True
    except Exception:
        return False


def export_env_snapshot(output_dir: Path, current_date: str) -> dict:
    """Export a lightweight environment snapshot to output_dir/snapshot-<MM-YY>.\n
    NOTE: This intentionally does NOT copy private SSH keys. It exports only public keys.
    """
    snapshot_dir = output_dir / f"snapshot-{current_date}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "snapshot_dir": str(snapshot_dir),
        "copied": [],
        "exported": [],
        "notes": []
    }

    home = Path(os.path.expanduser('~'))

    # ---- SSH (public keys only) ----
    ssh_dir = home / '.ssh'
    ssh_export_dir = snapshot_dir / 'ssh'
    ssh_export_dir.mkdir(parents=True, exist_ok=True)

    copied_any_pub = False
    for pub in ['id_rsa.pub', 'id_ed25519.pub', 'id_ecdsa.pub', 'id_dsa.pub', 'authorized_keys', 'known_hosts', 'config']:
        if safe_copy_file(ssh_dir / pub, ssh_export_dir):
            copied_any_pub = True
            results["copied"].append(f"ssh/{pub}")

    # Export all public keys via ssh-add -L (if agent has them) or by concatenating *.pub
    ssh_pub_out = ssh_export_dir / 'public_keys.txt'
    if run_cmd_to_file(['ssh-add', '-L'], ssh_pub_out):
        results["exported"].append('ssh/public_keys.txt (ssh-add -L)')
    else:
        try:
            pubs = sorted([p for p in ssh_dir.glob('*.pub') if p.is_file()])
            with open(ssh_pub_out, 'w', encoding='utf-8') as f:
                for p in pubs:
                    f.write(f"# {p.name}\n")
                    f.write(p.read_text(encoding='utf-8', errors='ignore'))
                    if not f.tell() or not str(p.read_text).endswith('\n'):
                        f.write('\n')
                    f.write('\n')
            if pubs:
                results["exported"].append('ssh/public_keys.txt (*.pub)')
        except Exception:
            pass

    if not copied_any_pub:
        results["notes"].append('No SSH public key files found in ~/.ssh (this may be OK if you use a different key name).')

    # ---- Git config ----
    git_dir = snapshot_dir / 'git'
    if safe_copy_file(home / '.gitconfig', git_dir):
        results["copied"].append('git/.gitconfig')
    if safe_copy_file(home / '.git-credentials', git_dir):
        results["copied"].append('git/.git-credentials')
    if safe_copy_dir(home / '.config' / 'gh', git_dir / '.config'):
        results["copied"].append('git/.config/gh (GitHub CLI)')

    # ---- Shell / terminal configs ----
    shell_dir = snapshot_dir / 'shell'
    for fname in ['.zshrc', '.zprofile', '.bashrc', '.bash_profile', '.profile', '.p10k.zsh']:
        if safe_copy_file(home / fname, shell_dir):
            results["copied"].append(f"shell/{fname}")

    # ---- VS Code user settings ----
    vscode_user = home / 'Library' / 'Application Support' / 'Code' / 'User'
    vscode_dir = snapshot_dir / 'vscode'
    if safe_copy_file(vscode_user / 'settings.json', vscode_dir):
        results["copied"].append('vscode/settings.json')
    if safe_copy_file(vscode_user / 'keybindings.json', vscode_dir):
        results["copied"].append('vscode/keybindings.json')
    if safe_copy_dir(vscode_user / 'snippets', vscode_dir):
        results["copied"].append('vscode/snippets/')

    # ---- LaunchAgents (your automations) ----
    launchagents = home / 'Library' / 'LaunchAgents'
    la_dir = snapshot_dir / 'launchd'
    if safe_copy_dir(launchagents, la_dir):
        results["copied"].append('launchd/LaunchAgents/')

    # ---- macOS preferences export (lightweight, most useful domains) ----
    defaults_dir = snapshot_dir / 'macos_defaults'
    for domain, outname in [
        ('-g', 'global.txt'),
        ('com.apple.dock', 'dock.txt'),
        ('com.apple.finder', 'finder.txt'),
        ('com.apple.trackpad', 'trackpad.txt'),
        ('com.apple.screencapture', 'screencapture.txt'),
        ('NSGlobalDomain', 'nsglobaldomain.txt')
    ]:
        if run_cmd_to_file(['defaults', 'read', domain], defaults_dir / outname):
            results["exported"].append(f"macos_defaults/{outname}")

    # ---- Python packages (current interpreter) ----
    py_dir = snapshot_dir / 'python'
    if run_cmd_to_file([sys.executable, '-m', 'pip', 'freeze'], py_dir / 'pip-freeze.txt'):
        results["exported"].append('python/pip-freeze.txt')

    # ---- Directory layout map (non-Dropbox) ----
    try:
        generate_directory_map(home, snapshot_dir)
        results["exported"].append('directory_map.txt')
    except Exception:
        results["notes"].append('Failed to generate directory map')

    # Manifest
    manifest = snapshot_dir / 'MANIFEST.md'
    with open(manifest, 'w', encoding='utf-8') as m:
        m.write(f"# Environment Snapshot ({current_date})\n\n")
        m.write(f"Created: {datetime.now().isoformat()}\n\n")
        m.write("## What this includes\n")
        m.write("- SSH: public keys only (NO private keys)\n")
        m.write("- Git: .gitconfig, GitHub CLI config (if present)\n")
        m.write("- Shell: zsh/bash config files (if present)\n")
        m.write("- VS Code: settings/keybindings/snippets (if present)\n")
        m.write("- launchd: ~/Library/LaunchAgents\n")
        m.write("- macOS defaults: a few common domains\n")
        m.write("- Python: pip freeze for the interpreter running this script\n\n")
        m.write("## Copied\n")
        for item in results['copied']:
            m.write(f"- {item}\n")
        m.write("\n## Exported\n")
        for item in results['exported']:
            m.write(f"- {item}\n")
        if results['notes']:
            m.write("\n## Notes\n")
            for n in results['notes']:
                m.write(f"- {n}\n")

    results["exported"].append('MANIFEST.md')
    return results

def generate_directory_map(home: Path, snapshot_dir: Path, max_depth: int = 3):
    """Create a readable directory layout (excluding Dropbox and noisy folders)."""
    ignore_dirs = {
        'Library', 'Applications', 'System', 'Volumes', '.Trash',
        'node_modules', '.git', '.venv', '__pycache__'
    }
    dropbox_path = home / 'Library' / 'CloudStorage' / 'Dropbox'

    out_file = snapshot_dir / 'directory_map.txt'
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(f"Directory map for {home}\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")

        def walk_dir(base: Path, depth: int):
            if depth > max_depth:
                return
            try:
                entries = sorted([p for p in base.iterdir() if not p.name.startswith('.') or p.name in {'.ssh', '.config'}])
            except Exception:
                return
            for p in entries:
                if p in dropbox_path.parents or str(p).startswith(str(dropbox_path)):
                    continue
                if p.name in ignore_dirs:
                    continue
                indent = '  ' * depth
                f.write(f"{indent}{p.name}/\n" if p.is_dir() else f"{indent}{p.name}\n")
                if p.is_dir():
                    walk_dir(p, depth + 1)

        walk_dir(home, 0)

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
            r.write("Install mas if needed: brew install mas\n")
            r.write("Sign into the App Store, then run:\n\n``\nmas install $(mas list | awk '{print $1}')\n``\n\n")
            r.write("## 4. Notes\n")
            r.write("This file was auto-generated by app_lister.\n")

        print(f"Created reinstall instructions: {readme_file}")
        
        snapshot_results = export_env_snapshot(output_dir, current_date)
        print(f"Created environment snapshot folder: {snapshot_results['snapshot_dir']}")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_installed_apps()