def _normalize_excel_url(url: str) -> str:
    """Normaliza links populares para download direto (Sheets/Drive/Dropbox/OneDrive)."""
    u = (url or "").strip()
    if not u:
        return u

    # Dropbox: força dl=1
    if "dropbox.com" in u:
        if "dl=0" in u:
            u = u.replace("dl=0", "dl=1")
        elif "dl=1" not in u and "raw=1" not in u:
            sep = "&" if "?" in u else "?"
            u = f"{u}{sep}dl=1"

    # Google Drive/Sheets → export xlsx (respeita gid quando houver)
    if "drive.google.com" in u or "docs.google.com" in u:
        import re as _re
        m = _re.search(r"/d/([a-zA-Z0-9_-]{20,})", u) or _re.search(r"[?&]id=([a-zA-Z0-9_-]{20,})", u)
        gid = None
        mg = _re.search(r"[?&#]gid=(\d+)", u)
        if mg:
            gid = mg.group(1)
        if m:
            fid = m.group(1)
            u = f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx&id={fid}"
            if gid:
                u = f"{u}&gid={gid}"

    # OneDrive/SharePoint: adiciona download=1
    if "onedrive.live.com" in u or "sharepoint.com" in u:
        sep = "&" if "?" in u else "?"
        u = f"{u}{sep}download=1"

    return u
