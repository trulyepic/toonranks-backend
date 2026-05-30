import re
from typing import List

# Matches @username where username is 3-20 chars: letters, digits, underscores, hyphens
MENTION_RE = re.compile(r"@([A-Za-z0-9_-]{3,20})")


def extract_mentions(text: str) -> List[str]:
    """Return a deduplicated list of lowercased usernames mentioned in text."""
    return list({m.lower() for m in MENTION_RE.findall(text)})
