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

    # ---- iTerm2 preferences ----
    iterm2_dir = snapshot_dir / 'iterm2'
    # Export as readable XML plist (best for diff / inspection)
    iterm2_plist = home / 'Library' / 'Preferences' / 'com.googlecode.iterm2.plist'
    if run_cmd_to_file(
        ['defaults', 'export', 'com.googlecode.iterm2', '-'],
        iterm2_dir / 'com.googlecode.iterm2.plist'
    ):
        results["exported"].append('iterm2/com.googlecode.iterm2.plist (defaults export)')
    elif safe_copy_file(iterm2_plist, iterm2_dir):
        results["copied"].append('iterm2/com.googlecode.iterm2.plist (binary copy)')
    else:
        results["notes"].append('iTerm2 plist not found — iTerm2 may not be installed.')

    # Also copy any dynamic profiles and color presets
    iterm2_app_support = home / 'Library' / 'Application Support' / 'iTerm2'
    for sub in ['DynamicProfiles', 'Scripts']:
        subpath = iterm2_app_support / sub
        if subpath.exists():
            if safe_copy_dir(subpath, iterm2_dir):
                results["copied"].append(f"iterm2/{sub}/")

    # ---- Warp terminal config ----
    warp_src = home / '.warp'
    if safe_copy_dir(warp_src, snapshot_dir):
        results["copied"].append('.warp/ (Warp config)')
    else:
        results["notes"].append('~/.warp not found — Warp may not be installed or not yet configured.')

    # ---- Keyboard Maestro macros ----
    km_src = home / 'Library' / 'Application Support' / 'Keyboard Maestro' / 'Keyboard Maestro Macros.kmmacros'
    km_dir = snapshot_dir / 'keyboard_maestro'
    if safe_copy_file(km_src, km_dir):
        results["copied"].append('keyboard_maestro/Keyboard Maestro Macros.kmmacros')
    else:
        results["notes"].append('Keyboard Maestro Macros.kmmacros not found — KM may not be installed.')

    # ---- Sublime Text user settings ----
    sublime_src = home / 'Library' / 'Application Support' / 'Sublime Text' / 'Packages' / 'User'
    sublime_dir = snapshot_dir / 'sublime_text'
    if safe_copy_dir(sublime_src, sublime_dir):
        results["copied"].append('sublime_text/User/ (Sublime Text settings)')
    else:
        results["notes"].append('Sublime Text User folder not found — may not be installed.')

    # ---- Rectangle window manager preferences ----
    defaults_dir_rect = snapshot_dir / 'rectangle'
    if run_cmd_to_file(['defaults', 'export', 'com.knollsoft.Rectangle', '-'], defaults_dir_rect / 'com.knollsoft.Rectangle.plist'):
        results["exported"].append('rectangle/com.knollsoft.Rectangle.plist')
    else:
        results["notes"].append('Rectangle preferences not found — may not be installed.')

    # ---- npm global packages ----
    npm_dir = snapshot_dir / 'npm'
    npm_path = shutil.which('npm', path=os.environ.get('PATH', '') + ':/opt/homebrew/bin:/usr/local/bin')
    if npm_path and run_cmd_to_file([npm_path, 'list', '-g', '--depth=0'], npm_dir / 'npm-globals.txt'):
        results["exported"].append('npm/npm-globals.txt')
    else:
        results["notes"].append('npm not found or npm list -g failed.')

    # ---- Conda environments ----
    conda_dir = snapshot_dir / 'conda'
    conda_path = shutil.which('conda', path=os.environ.get('PATH', '') + ':/opt/homebrew/bin:/opt/miniconda3/bin:/usr/local/bin')
    if conda_path:
        # List all envs
        env_list_result = subprocess.run([conda_path, 'env', 'list', '--json'], capture_output=True, text=True)
        if env_list_result.returncode == 0:
            import json
            try:
                env_data = json.loads(env_list_result.stdout)
                env_paths = env_data.get('envs', [])
                conda_dir.mkdir(parents=True, exist_ok=True)
                exported_envs = []
                for env_path in env_paths:
                    env_name = Path(env_path).name  # 'base', 'myenv', etc.
                    out_file = conda_dir / f"{env_name}.yml"
                    r = subprocess.run([conda_path, 'env', 'export', '-p', env_path], capture_output=True, text=True)
                    if r.returncode == 0:
                        out_file.write_text(r.stdout, encoding='utf-8')
                        exported_envs.append(f"conda/{env_name}.yml")
                results["exported"].extend(exported_envs)
                if not exported_envs:
                    results["notes"].append('Conda found but no environments exported.')
            except Exception:
                results["notes"].append('Conda env export failed (JSON parse error).')
    else:
        results["notes"].append('conda not found in PATH — miniconda may not be activated.')

    # ---- Custom fonts (manually installed, not covered by Brewfile) ----
    user_fonts_src = home / 'Library' / 'Fonts'
    fonts_dir = snapshot_dir / 'fonts'
    if user_fonts_src.exists() and any(user_fonts_src.iterdir()):
        if safe_copy_dir(user_fonts_src, fonts_dir):
            results["copied"].append('fonts/Fonts/ (~/Library/Fonts)')
    else:
        results["notes"].append('~/Library/Fonts is empty — all fonts likely covered by Brewfile casks.')

    # ---- /etc/hosts (custom entries) ----
    hosts_dir = snapshot_dir / 'network'
    if safe_copy_file(Path('/etc/hosts'), hosts_dir):
        results["copied"].append('network/hosts')

    # ---- macOS computer name ----
    system_dir = snapshot_dir / 'system'
    system_dir.mkdir(parents=True, exist_ok=True)
    try:
        computer_name = subprocess.run(['scutil', '--get', 'ComputerName'], capture_output=True, text=True).stdout.strip()
        local_hostname = subprocess.run(['scutil', '--get', 'LocalHostName'], capture_output=True, text=True).stdout.strip()
        hostname = subprocess.run(['scutil', '--get', 'HostName'], capture_output=True, text=True).stdout.strip()
        with open(system_dir / 'computer_name.txt', 'w', encoding='utf-8') as f:
            f.write(f"ComputerName:  {computer_name}\n")
            f.write(f"LocalHostName: {local_hostname}\n")
            f.write(f"HostName:      {hostname}\n")
            f.write("\nTo restore on new Mac:\n")
            f.write(f"  sudo scutil --set ComputerName '{computer_name}'\n")
            f.write(f"  sudo scutil --set LocalHostName '{local_hostname}'\n")
            if hostname:
                f.write(f"  sudo scutil --set HostName '{hostname}'\n")
        results["exported"].append('system/computer_name.txt')
    except Exception:
        results["notes"].append('Could not read computer name via scutil.')

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
        m.write("- iTerm2: preferences plist, dynamic profiles, scripts (if installed)\n")
        m.write("- Warp: ~/.warp/ config directory (if installed)\n")
        m.write("- Keyboard Maestro: Keyboard Maestro Macros.kmmacros (if installed)\n")
        m.write("- Sublime Text: Packages/User/ settings folder (if installed)\n")
        m.write("- Rectangle: preferences plist (if installed)\n")
        m.write("- npm: global packages list (if installed)\n")
        m.write("- Conda: exported .yml for each environment (if installed)\n")
        m.write("- Fonts: ~/Library/Fonts (manually installed fonts not in Brewfile)\n")
        m.write("- Network: /etc/hosts\n")
        m.write("- System: computer name / hostname\n")
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

def collect_python_project_repos(projects_dir: Path) -> list[dict]:
    """Scan projects_dir for git repos and return list of {name, folder, remote, ssh_remote}."""
    repos = []
    if not projects_dir.exists():
        return repos
    for item in sorted(projects_dir.iterdir()):
        if not item.is_dir():
            continue
        git_dir = item / '.git'
        if not git_dir.exists():
            continue
        try:
            result = subprocess.run(
                ['git', '-C', str(item), 'remote', 'get-url', 'origin'],
                capture_output=True, text=True
            )
            remote = result.stdout.strip() if result.returncode == 0 else ''
            # Convert HTTPS to SSH format for cloning on new Mac
            ssh_remote = remote
            if remote.startswith('https://github.com/'):
                path_part = remote.replace('https://github.com/', '')
                ssh_remote = f"git@github.com:{path_part}"
            repos.append({
                'name': item.name,
                'folder': item.name,
                'remote': remote,
                'ssh_remote': ssh_remote,
            })
        except Exception:
            continue
    return repos


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

        # Collect Python project repos for README
        python_projects_dir = Path(os.path.expanduser('~/PythonProjects'))
        python_repos = collect_python_project_repos(python_projects_dir)

        # Create reinstall instructions markdown
        readme_file = output_dir / "README-Reinstall.md"
        snapshot_subdir = f"snapshot-{current_date}"
        with open(readme_file, 'w', encoding='utf-8') as r:
            r.write(f"# Mac Reinstall Instructions\n\n")
            r.write(f"_Auto-generated {datetime.now().strftime('%B %Y')} by app_lister. Work through steps in order._\n\n")
            r.write("---\n\n")

            r.write("## 1. First Things First\n\n")
            r.write("- Connect to Wi-Fi — the rest of this process is download-heavy\n")
            r.write("- Sign into iCloud (System Settings → Apple ID)\n")
            r.write("- Sign into the Mac App Store (needed for MAS installs in step 6)\n\n")
            r.write("### Install Dropbox and wait for sync — do this before anything else\n\n")
            r.write("All your snapshot files, Brewfile, and this README live in Dropbox.\n")
            r.write("You need Dropbox synced before step 3 will work.\n\n")
            r.write("1. Download Dropbox from https://www.dropbox.com/install (do NOT use brew yet — the Brewfile is in Dropbox)\n")
            r.write("2. Install and sign in\n")
            r.write(f'3. Wait for the `Mac Installed Apps` folder to finish syncing — check that this file exists:\n')
            r.write(f'   `{output_dir}/README-Reinstall.md`\n')
            r.write("4. Once that folder is synced, proceed to step 2\n\n")
            r.write("> **Shortcut:** If Dropbox is slow, you can also clone `github.com/alexkharrod/app_lister` and use the static `Brewfile` in that repo for step 3, then come back for the snapshot files once Dropbox catches up.\n\n")

            r.write("## 2. Install Homebrew\n\n")
            r.write("```bash\n")
            r.write('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n')
            r.write("```\n\n")
            r.write("After install, follow the instructions to add brew to your PATH (shown at end of install output).\n\n")

            r.write("## 3. Restore Homebrew Packages & Apps\n\n")
            r.write("This installs all formulae, casks, and VS Code extensions from the Brewfile snapshot.\n\n")
            r.write("```bash\n")
            r.write(f'brew bundle install --file "{output_dir}/{brewfile.name}"\n')
            r.write("```\n\n")
            r.write("> Note: Some casks may ask for your password or require manual approval in System Settings → Privacy & Security.\n\n")

            r.write("## 4. Restore Custom Fonts\n\n")
            r.write("Fonts installed via Homebrew casks are already handled by step 3.\n")
            r.write("This step covers any fonts you manually installed into ~/Library/Fonts.\n\n")
            r.write("```bash\n")
            r.write(f'cp -r "{output_dir}/{snapshot_subdir}/fonts/Fonts/"* ~/Library/Fonts/\n')
            r.write("```\n\n")
            r.write("> Skip this step if the `fonts/Fonts/` folder in the snapshot is empty.\n\n")

            r.write("## 5. Restore Shell Configuration\n\n")
            r.write("```bash\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/shell/.zshrc" ~/.zshrc\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/shell/.zprofile" ~/.zprofile   # if it exists\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/shell/.p10k.zsh" ~/.p10k.zsh   # if using Powerlevel10k\n')
            r.write("source ~/.zshrc\n")
            r.write("```\n\n")

            r.write("## 6. Mac App Store Apps\n\n")
            r.write("```bash\n")
            r.write("# Install mas if not already in Brewfile\n")
            r.write("brew install mas\n\n")
            r.write(f"# Re-install MAS apps (see {output_dir}/installed_apps-{current_date}.txt for the list)\n")
            r.write("# Find each app's ID at https://apps.apple.com and run:\n")
            r.write("# mas install <APP_ID>\n")
            r.write("```\n\n")

            r.write("## 7. Restore iTerm2 Settings\n\n")
            r.write("```bash\n")
            r.write(f'# Import preferences (restores colors, profiles, keybindings)\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/iterm2/com.googlecode.iterm2.plist" \\\n')
            r.write('   ~/Library/Preferences/com.googlecode.iterm2.plist\n\n')
            r.write("# Restore Dynamic Profiles if present\n")
            r.write(f'cp -r "{output_dir}/{snapshot_subdir}/iterm2/DynamicProfiles" \\\n')
            r.write('   ~/Library/Application\\ Support/iTerm2/DynamicProfiles\n')
            r.write("```\n\n")
            r.write("Then open iTerm2 → Preferences → General → Preferences and point it at this plist for future auto-sync.\n\n")

            r.write("## 8. Restore Warp Terminal Config\n\n")
            r.write("```bash\n")
            r.write(f'cp -r "{output_dir}/{snapshot_subdir}/.warp" ~/.warp\n')
            r.write("```\n\n")

            r.write("## 9. Restore Keyboard Maestro Macros\n\n")
            r.write("1. Open Keyboard Maestro\n")
            r.write("2. File → Import Macros → select the file below:\n")
            r.write(f'   `{output_dir}/{snapshot_subdir}/keyboard_maestro/Keyboard Maestro Macros.kmmacros`\n\n')
            r.write("   Or from the terminal:\n")
            r.write("```bash\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/keyboard_maestro/Keyboard Maestro Macros.kmmacros" \\\n')
            r.write('   ~/Library/Application\\ Support/Keyboard\\ Maestro/\n')
            r.write("# Then relaunch Keyboard Maestro for it to pick up the macros\n")
            r.write("```\n\n")

            r.write("## 10. Restore Sublime Text Settings\n\n")
            r.write("```bash\n")
            r.write('SUBLIME_USER="$HOME/Library/Application Support/Sublime Text/Packages/User"\n')
            r.write('mkdir -p "$SUBLIME_USER"\n')
            r.write(f'cp -r "{output_dir}/{snapshot_subdir}/sublime_text/User/"* "$SUBLIME_USER/"\n')
            r.write("```\n\n")
            r.write("Open Sublime Text → Tools → Install Package Control (if not already there), then install any packages listed in `Package Control.sublime-settings`.\n\n")

            r.write("## 11. Restore Rectangle Preferences\n\n")
            r.write("```bash\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/rectangle/com.knollsoft.Rectangle.plist" \\\n')
            r.write('   ~/Library/Preferences/com.knollsoft.Rectangle.plist\n')
            r.write("# Then relaunch Rectangle\n")
            r.write("```\n\n")

            r.write("## 12. Restore npm Global Packages\n\n")
            r.write(f"Reference: `{output_dir}/{snapshot_subdir}/npm/npm-globals.txt`\n\n")
            r.write("```bash\n")
            r.write(f'cat "{output_dir}/{snapshot_subdir}/npm/npm-globals.txt"\n')
            r.write("# Then reinstall each package, e.g.:\n")
            r.write("# npm install -g <package-name>\n")
            r.write("```\n\n")

            r.write("## 13. Restore Conda Environments\n\n")
            r.write(f"Exported .yml files are in: `{output_dir}/{snapshot_subdir}/conda/`\n\n")
            r.write("```bash\n")
            r.write(f'for yml in "{output_dir}/{snapshot_subdir}/conda/"*.yml; do\n')
            r.write('    conda env create -f "$yml"\n')
            r.write('done\n')
            r.write("```\n\n")
            r.write("> Note: `base.yml` contains the base conda environment — you can skip recreating it as a named env; it just serves as a reference.\n\n")

            r.write("## 14. Restore /etc/hosts\n\n")
            r.write("```bash\n")
            r.write(f'# Review your old hosts file first:\n')
            r.write(f'cat "{output_dir}/{snapshot_subdir}/network/hosts"\n\n')
            r.write("# Merge any custom entries into the new Mac's hosts file:\n")
            r.write("sudo nano /etc/hosts\n")
            r.write("```\n\n")
            r.write("> Don't blindly overwrite — the new Mac's hosts file already has required system entries.\n\n")

            r.write("## 15. Restore Git & SSH Config\n\n")
            r.write("### Git config\n\n")
            r.write("```bash\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/git/.gitconfig" ~/.gitconfig\n')
            r.write("```\n\n")
            r.write("### SSH public key + config\n\n")
            r.write("```bash\n")
            r.write("mkdir -p ~/.ssh\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/ssh/config" ~/.ssh/config\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/ssh/known_hosts" ~/.ssh/known_hosts\n')
            r.write("chmod 700 ~/.ssh\n")
            r.write("chmod 600 ~/.ssh/config\n")
            r.write("```\n\n")
            r.write("### SSH private key — choose one option\n\n")
            r.write("**Option 1 (recommended) — Generate a fresh key on the new Mac:**\n\n")
            r.write("```bash\n")
            r.write('ssh-keygen -t ed25519 -C "alexkharrod@gmail.com"\n')
            r.write("gh auth login   # uploads the new key to GitHub automatically\n")
            r.write("```\n\n")
            r.write("Then add the new key to any other services you use SSH with (servers, hosting, etc.).\n\n")
            r.write("**Option 2 — AirDrop the private key from old Mac:**\n\n")
            r.write("On the old Mac: open Finder → Go → ~/.ssh → AirDrop `id_ed25519` to new Mac.\n\n")
            r.write("```bash\n")
            r.write("# On new Mac, after receiving via AirDrop:\n")
            r.write("mv ~/Downloads/id_ed25519 ~/.ssh/id_ed25519\n")
            r.write("chmod 600 ~/.ssh/id_ed25519\n")
            r.write("ssh-add ~/.ssh/id_ed25519\n")
            r.write("```\n\n")
            r.write("**Option 3 — Retrieve from 1Password:**\n\n")
            r.write("If you stored the private key as a secure note in 1Password, copy it out and save to `~/.ssh/id_ed25519`, then run `chmod 600 ~/.ssh/id_ed25519`.\n\n")
            r.write("> **Private keys are NOT in the snapshot** — they are intentionally excluded for security.\n\n")

            r.write("## 16. Restore VS Code Settings\n\n")
            r.write("```bash\n")
            r.write('VSCODE_USER="$HOME/Library/Application Support/Code/User"\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/vscode/settings.json" "$VSCODE_USER/settings.json"\n')
            r.write(f'cp "{output_dir}/{snapshot_subdir}/vscode/keybindings.json" "$VSCODE_USER/keybindings.json"\n')
            r.write(f'cp -r "{output_dir}/{snapshot_subdir}/vscode/snippets" "$VSCODE_USER/snippets"\n')
            r.write("```\n\n")
            r.write("VS Code extensions are already handled by `brew bundle` (step 3).\n\n")

            r.write("## 17. Restore LaunchAgents (Automations)\n\n")
            r.write("```bash\n")
            r.write(f'cp "{output_dir}/{snapshot_subdir}/launchd/LaunchAgents/"*.plist ~/Library/LaunchAgents/\n\n')
            r.write("# Load each one (replace <label> with the plist filename without .plist)\n")
            r.write("launchctl load ~/Library/LaunchAgents/<label>.plist\n")
            r.write("```\n\n")
            r.write("Key LaunchAgents to check:\n")
            r.write("- `com.logoinluded.ptool-backup.plist` — nightly DB backup to Dropbox\n\n")

            r.write("## 18. Clone Python Projects\n\n")
            r.write("```bash\n")
            r.write("mkdir -p ~/PythonProjects && cd ~/PythonProjects\n\n")
            if python_repos:
                for repo in python_repos:
                    folder = repo['folder']
                    ssh = repo['ssh_remote']
                    # Quote folder name in case it has spaces
                    r.write(f'git clone "{ssh}" "{folder}"\n')
            else:
                r.write("# No git repos found in ~/PythonProjects at snapshot time\n")
            r.write("```\n\n")
            r.write("> Make sure SSH is set up first (step 14) and your key is added to GitHub before cloning via SSH.\n\n")

            r.write("## 19. ptool (Internal Product Tool) Setup\n\n")
            r.write("```bash\n")
            r.write("cd ~/PythonProjects\n")
            r.write("git clone git@github.com:<your-repo>/ptool.git\n")
            r.write("cd ptool\n")
            r.write("python -m venv .venv && source .venv/bin/activate\n")
            r.write("pip install -r requirements.txt\n\n")
            r.write("# Create .env with credentials from 1Password:\n")
            r.write("cat > .env <<'EOF'\n")
            r.write("SECRET_KEY=...\n")
            r.write("DEBUG=False\n")
            r.write("DATABASE_URL=postgresql://...\n")
            r.write("CLOUDINARY_URL=cloudinary://...\n")
            r.write("ALLOWED_HOSTS=...\n")
            r.write("EOF\n\n")
            r.write("python manage.py migrate\n")
            r.write("python manage.py runserver\n")
            r.write("```\n\n")

            r.write("## 20. Set Computer Name\n\n")
            r.write(f"Your previous computer name is saved in: `{output_dir}/{snapshot_subdir}/system/computer_name.txt`\n\n")
            r.write("```bash\n")
            r.write(f'cat "{output_dir}/{snapshot_subdir}/system/computer_name.txt"\n\n')
            r.write("# Apply the names (replace values with what's in the file above):\n")
            r.write("sudo scutil --set ComputerName 'Your Mac Name'\n")
            r.write("sudo scutil --set LocalHostName 'Your-Mac-Name'\n")
            r.write("```\n\n")

            r.write("## 21. Restore macOS System Preferences\n\n")
            r.write("The `macos_defaults/` folder in the snapshot contains exported preferences for Dock, Finder, Trackpad, etc.\n")
            r.write("These are for reference — review and apply selectively:\n\n")
            r.write("```bash\n")
            r.write(f'cat "{output_dir}/{snapshot_subdir}/macos_defaults/dock.txt"\n')
            r.write("# Then apply individual settings as needed, e.g.:\n")
            r.write("# defaults write com.apple.dock autohide -bool true && killall Dock\n")
            r.write("```\n\n")

            r.write("---\n\n")
            r.write("_This file is auto-generated by `app_lister.py`. Re-run it on your current machine to refresh the snapshot._\n")

        print(f"Created reinstall instructions: {readme_file}")
        
        snapshot_results = export_env_snapshot(output_dir, current_date)
        print(f"Created environment snapshot folder: {snapshot_results['snapshot_dir']}")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_installed_apps()