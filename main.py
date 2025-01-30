import os
from datetime import datetime
import subprocess

def get_brew_packages():
    try:
        # Run 'brew list --formula' to get non-cask packages
        result = subprocess.run(['brew', 'list', '--formula'], capture_output=True, text=True)
        if result.returncode == 0:
            # Split the output into a list and sort it
            return sorted(result.stdout.strip().split('\n'))
        return []
    except FileNotFoundError:
        print("Homebrew not found. Skipping brew packages.")
        return []

def get_installed_apps():
    # Define the applications directory path
    apps_dir = "/Applications"
    
    # Get current date for filename
    current_date = datetime.now().strftime("%m-%y")
    output_file = f"installed_apps-{current_date}.txt"
    
    # Get list of all .app files
    apps = []
    try:
        # Walk through the Applications directory
        for item in os.listdir(apps_dir):
            if item.endswith('.app'):
                apps.append(item)
        
        # Sort alphabetically
        apps.sort()
        
        # Get Homebrew packages
        brew_packages = get_brew_packages()
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"System Report as of {datetime.now().strftime('%B %Y')}\n")
            f.write("=" * 50 + "\n\n")
            
            # Write Applications
            f.write("Applications (.app)\n")
            f.write("-" * 50 + "\n")
            for app in apps:
                f.write(f"{app}\n")
            
            # Write Homebrew packages
            f.write("\nHomebrew Packages (non-cask)\n")
            f.write("-" * 50 + "\n")
            for package in brew_packages:
                f.write(f"{package}\n")
                
        print(f"Successfully created {output_file}")
        print(f"Found {len(apps)} applications and {len(brew_packages)} Homebrew packages.")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_installed_apps()