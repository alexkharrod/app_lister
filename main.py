import os
from datetime import datetime
import subprocess

def get_brew_packages():
    try:
        # Get regular brew formulae
        result = subprocess.run(['brew', 'list', '--formula'], capture_output=True, text=True)
        packages = sorted(result.stdout.strip().split('\n')) if result.returncode == 0 else []
        
        # Create Brewfile for reinstallation
        brewfile_result = subprocess.run(['brew', 'bundle', 'dump'], capture_output=True, text=True)
        brewfile_content = brewfile_result.stdout if brewfile_result.returncode == 0 else ""
        
        return packages, brewfile_content
    except FileNotFoundError:
        print("Homebrew not found. Skipping brew packages.")
        return [], ""

def get_installed_apps():
    # Define the applications directory path
    apps_dir = "/Applications"
    
    # Get current date for filename
    current_date = datetime.now().strftime("%m-%y")
    output_file = f"installed_apps-{current_date}.txt"
    brewfile = f"Brewfile-{current_date}"
    
    try:
        # Get .app files
        apps = sorted([item for item in os.listdir(apps_dir) if item.endswith('.app')])
        
        # Get Homebrew packages and Brewfile content
        brew_packages, brewfile_content = get_brew_packages()
        
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
            
            f.write("\nNOTE: A Brewfile has been created that can be used to reinstall all Homebrew packages.\n")
            f.write("To reinstall using the Brewfile, run: brew bundle install --file Brewfile-MM-YY\n")
        
        # Write Brewfile
        if brewfile_content:
            with open(brewfile, 'w', encoding='utf-8') as f:
                f.write(brewfile_content)
            print(f"Created {brewfile} for package reinstallation")
                
        print(f"Successfully created {output_file}")
        print(f"Found {len(apps)} applications and {len(brew_packages)} Homebrew packages.")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_installed_apps()