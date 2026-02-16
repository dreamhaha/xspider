#!/usr/bin/env python3
"""
Extract email addresses from user bios.

Usage:
    python scripts/extract_emails.py
"""

import asyncio
import sys
import csv
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Email regex pattern - handles various formats
EMAIL_PATTERNS = [
    # Standard email
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    # Obfuscated emails: user [at] domain [dot] com
    re.compile(r'\b[A-Za-z0-9._%+-]+\s*[\[\(]?\s*(?:at|AT|@)\s*[\]\)]?\s*[A-Za-z0-9.-]+\s*[\[\(]?\s*(?:dot|DOT|\.)\s*[\]\)]?\s*[A-Za-z]{2,}\b'),
    # user (at) domain.com
    re.compile(r'\b[A-Za-z0-9._%+-]+\s*\(at\)\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', re.IGNORECASE),
]


def extract_emails(text: str) -> list[str]:
    """Extract email addresses from text."""
    if not text:
        return []

    emails = set()

    # More precise email pattern - requires proper structure
    # username: alphanumeric, dots, underscores, hyphens (min 2 chars)
    # domain: alphanumeric with dots (min 2 parts)
    # tld: 2-6 letters
    precise_email_pattern = re.compile(
        r'\b([A-Za-z0-9][A-Za-z0-9._%+-]{1,}@[A-Za-z0-9][A-Za-z0-9.-]+\.[A-Za-z]{2,6})\b'
    )

    for match in precise_email_pattern.finditer(text):
        email = match.group(1).lower()
        local_part, domain = email.split('@')

        # Validate local part (username)
        # - Must not start/end with dot
        # - Must not have consecutive dots
        if local_part.startswith('.') or local_part.endswith('.'):
            continue
        if '..' in local_part:
            continue

        # Validate domain
        # - Must have at least one dot
        # - Parts must be at least 2 chars
        domain_parts = domain.split('.')
        if len(domain_parts) < 2:
            continue
        if any(len(part) < 2 for part in domain_parts):
            continue

        # Filter out common false positives from Twitter bios
        # These are often part of words that got matched
        false_positive_locals = [
            'applic', 'candid', 'ceo', 'for', 'things', 'robotics',
            'acceler', 'scientist', 'hacker',
        ]
        if local_part in false_positive_locals:
            continue

        # Filter invalid domains (parts of words)
        false_positive_domains = [
            'ions.', 'e.pure', 'you.com', 'ion.pytorch', 'nyu.co',
            'splice.', 'openai.', 'thinkymachines.',
        ]
        if any(fp in domain for fp in false_positive_domains):
            continue

        # Valid email
        emails.add(email)

    # Also check for obfuscated patterns like "user [at] domain [dot] com"
    obfuscated_pattern = re.compile(
        r'\b([A-Za-z0-9._%+-]+)\s*[\[\(]?\s*(?:at|AT)\s*[\]\)]?\s*'
        r'([A-Za-z0-9.-]+)\s*[\[\(]?\s*(?:dot|DOT)\s*[\]\)]?\s*'
        r'([A-Za-z]{2,6})\b'
    )

    for match in obfuscated_pattern.finditer(text):
        local_part, domain_name, tld = match.groups()
        email = f"{local_part.lower()}@{domain_name.lower()}.{tld.lower()}"
        emails.add(email)

    return list(emails)


async def extract_emails_from_bios():
    """Extract emails from the most recent users_with_bios file."""

    exports_dir = Path("data/exports")

    # Find the most recent users_with_bios file
    bio_files = sorted(exports_dir.glob("users_with_bios_*.csv"), reverse=True)

    if not bio_files:
        console.print("[red]No users_with_bios files found[/red]")
        return

    bio_file = bio_files[0]
    console.print(f"[cyan]Reading: {bio_file}[/cyan]")

    # Read users
    users = []
    with open(bio_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(row)

    console.print(f"[green]Found {len(users)} users[/green]")

    console.print(Panel(
        "[bold]Email Extraction[/bold]\n\n"
        "Extracting email addresses from user bios\n"
        "Handles obfuscated formats like:\n"
        "- user@domain.com\n"
        "- user [at] domain [dot] com\n"
        "- user(at)domain.com",
        title="📧 Email Extractor",
    ))

    # Extract emails
    users_with_emails = []
    total_emails = 0

    for user in users:
        description = user.get("description", "")
        emails = extract_emails(description)

        if emails:
            users_with_emails.append({
                "screen_name": user.get("screen_name", ""),
                "name": user.get("name", ""),
                "followers_count": user.get("followers_count", ""),
                "emails": emails,
                "description": description,
            })
            total_emails += len(emails)

    console.print(f"\n[green]Found {len(users_with_emails)} users with emails ({total_emails} total emails)[/green]")

    # Show results
    if users_with_emails:
        table = Table(title="Users with Email Addresses")
        table.add_column("Username", style="cyan")
        table.add_column("Name")
        table.add_column("Followers", justify="right")
        table.add_column("Email(s)", style="yellow")
        table.add_column("Bio Snippet", style="dim", max_width=30)

        for user in users_with_emails:
            bio_snippet = user["description"][:50] + "..." if len(user["description"]) > 50 else user["description"]
            table.add_row(
                f"@{user['screen_name']}",
                user["name"][:20],
                str(user["followers_count"]),
                "\n".join(user["emails"]),
                bio_snippet,
            )

        console.print(table)

        # Export results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        emails_file = exports_dir / f"user_emails_{timestamp}.csv"

        with open(emails_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "screen_name", "name", "followers_count", "email", "description"
            ])
            writer.writeheader()
            for user in users_with_emails:
                for email in user["emails"]:
                    writer.writerow({
                        "screen_name": user["screen_name"],
                        "name": user["name"],
                        "followers_count": user["followers_count"],
                        "email": email,
                        "description": user["description"].replace("\n", " ")[:200],
                    })

        console.print(f"\n✅ Exported to: [cyan]{emails_file}[/cyan]")
    else:
        console.print("[yellow]No email addresses found in user bios[/yellow]")

    # Summary
    console.print("\n" + "=" * 50)
    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green", justify="right")

    summary.add_row("Users Scanned", str(len(users)))
    summary.add_row("Users with Emails", str(len(users_with_emails)))
    summary.add_row("Total Emails Found", str(total_emails))

    console.print(summary)


if __name__ == "__main__":
    asyncio.run(extract_emails_from_bios())
