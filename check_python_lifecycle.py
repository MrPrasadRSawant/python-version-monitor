
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests
from packaging.version import Version

API_URL = "https://endoflife.date/api/v1/products/python"
CONFIG_FILE = Path("config.json")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")


def get_python_releases():
    """Get latest patches and EOL dates for every Python branch."""
    response = requests.get(API_URL, timeout=20)
    response.raise_for_status()

    data = response.json()
    releases = data["result"]["releases"]

    if not releases:
        raise ValueError("Python lifecycle API returned no releases")

    return releases


def get_recommended_version(releases):
    """
    Select a supported upgrade candidate with at least
    365 days of remaining security support.
    This is not a dependency-compatibility guarantee.
    """
    today = date.today()
    candidates = []

    for release in releases:
        latest = release.get("latest") or {}
        latest_version = latest.get("name")
        eol_date = release.get("eolFrom")

        if not latest_version or not eol_date:
            continue

        remaining = (date.fromisoformat(eol_date) - today).days

        if remaining >= 365 and not release.get("isEol"):
            candidates.append(latest_version)

    if not candidates:
        return None

    return str(max(candidates, key=Version))


def check_product(product, releases, recommended):
    """Check the installed version of one product."""
    installed = product["python_version"]
    name = product["name"]
    branch = ".".join(installed.split(".")[:2])

    release = next(
        (r for r in releases if r["name"] == branch),
        None
    )

    if release is None:
        return {
            "name": name,
            "installed": installed,
            "status": "UNKNOWN",
            "message": "Version branch not found in lifecycle API"
        }

    eol_value = release.get("eolFrom")
    if not eol_value:
        return {
            "name": name,
            "installed": installed,
            "status": "UNKNOWN",
            "message": "EOL date is not available"
        }

    today = date.today()
    eol = date.fromisoformat(eol_value)
    days_left = (eol - today).days

    latest = (release.get("latest") or {}).get("name")
    patch_available = (
        latest is not None
        and Version(latest) > Version(installed)
    )

    if days_left <= 0:
        status = "CRITICAL"
        message = "Python branch is end-of-life"
    elif days_left <= 90:
        status = "WARNING"
        message = f"Python branch reaches EOL in {days_left} days"
    elif patch_available:
        status = "UPDATE"
        message = "New Python patch is available"
    else:
        status = "HEALTHY"
        message = "No immediate action required"

    return {
        "name": name,
        "installed": installed,
        "branch": branch,
        "latest_patch": latest,
        "eol_date": eol.isoformat(),
        "days_to_eol": days_left,
        "status": status,
        "message": message,
        "recommended": recommended,
    }


def send_teams_notification(results):
    """Post a weekly report using a Teams Workflows webhook."""
    if not TEAMS_WEBHOOK_URL:
        print("TEAMS_WEBHOOK_URL missing. Skipping Teams notification.")
        return

    lines = ["Python Runtime Lifecycle Report", ""]

    for item in results:
        lines.extend([
            f"Product: {item['name']}",
            f"Status: {item['status']}",
            f"Installed: {item['installed']}",
            f"Latest patch: {item.get('latest_patch', 'Unknown')}",
            f"EOL date: {item.get('eol_date', 'Unknown')}",
            f"Recommended: {item.get('recommended') or 'Review manually'}",
            f"Action: {item['message']}",
            ""
        ])

    report = "\n".join(lines)

    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "Weekly Python Lifecycle Report",
                        "weight": "Bolder",
                        "size": "Large"
                    },
                    {
                        "type": "TextBlock",
                        "text": report,
                        "wrap": True
                    }
                ]
            }
        }]
    }

    response = requests.post(
        TEAMS_WEBHOOK_URL,
        json=payload,
        timeout=20
    )
    response.raise_for_status()
    print("Teams notification sent.")


def main():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    releases = get_python_releases()
    recommended = get_recommended_version(releases)

    results = []

    for product in config["products"]:
        result = check_product(product, releases, recommended)
        results.append(result)

        print(json.dumps(result, indent=2))

    send_teams_notification(results)

    print("Lifecycle monitoring completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
