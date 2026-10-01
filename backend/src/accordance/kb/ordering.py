import re


def natural_key(disclosure_id: str) -> list:
    """Sort key so '2-10' sorts after '2-2' (numeric segments compared as ints)."""
    return [int(p) if p.isdigit() else p for p in re.split(r"[-.]", disclosure_id)]
