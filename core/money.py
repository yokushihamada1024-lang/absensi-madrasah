"""Format uang Rupiah tanpa bergantung pada locale OS."""


def format_thousands(n: int) -> str:
    s = str(abs(int(n)))
    groups = []
    while s:
        groups.append(s[-3:])
        s = s[:-3]
    out = ".".join(reversed(groups)) or "0"
    return f"-{out}" if n < 0 else out


def format_rupiah(n: int) -> str:
    """1250000 → 'Rp 1.250.000'; -5000 → '-Rp 5.000'."""
    n = int(n)
    body = format_thousands(abs(n))
    return f"-Rp {body}" if n < 0 else f"Rp {body}"
