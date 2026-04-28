import json
import os
import subprocess
from datetime import datetime
from secrets import get_secret

# Local paths relative to the script
METRICS_PATH = "../data/metrics.json"

def run_git_update():
    """
    Automates the staging, committing, and pushing of the data file.
    """
    try:
        subprocess.run(["git", "add", METRICS_PATH], check=True)
        commit_msg = f"Dashboard Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("Successfully pushed updates to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {e}")

def main():
    # 1. Fetch keys
    api_key = get_secret("ANTHROPIC_API_KEY")
    
    # 2. Run analysis (your existing Claude logic here)
    print("Running AI analysis...")
    new_metrics = {
        "last_updated": datetime.now().isoformat(),
        "metrics": {
            "institutional": 75, # Example value
            "economic": 62,
            "civil_rights": 80,
            "distraction": 45,
            "gini": 41.2
        }
    }
    
    # 3. Write locally
    with open(METRICS_PATH, "w") as f:
        json.dump(new_metrics, f, indent=2)
    print(f"Local file {METRICS_PATH} updated.")

    # 4. Push to GitHub
    confirm = input("Push changes to GitHub? (y/n): ")
    if confirm.lower() == 'y':
        run_git_update()

if __name__ == "__main__":
    main()
