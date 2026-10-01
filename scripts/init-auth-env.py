"""Add missing local auth secrets without printing or replacing existing secrets."""

from pathlib import Path
import secrets


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "backend" / ".env"
    if not path.exists():
        raise SystemExit("Copy backend/.env.example to backend/.env first.")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    changed = False
    for key in ("AUTH_JWT_SECRET", "AUTH_RATE_LIMIT_SECRET"):
        matches = [index for index, line in enumerate(lines) if line.startswith(key + "=")]
        if len(matches) > 1:
            raise SystemExit(f"Remove duplicate {key} entries before initialization.")
        if matches:
            index = matches[0]
            value = lines[index].split("=", 1)[1].strip().strip('\"\'')
            if value and not value.startswith("replace-") and not value.startswith("CHANGE"):
                continue
            lines[index] = f"{key}={secrets.token_urlsafe(48)}"
        else:
            lines.append(f"{key}={secrets.token_urlsafe(48)}")
        changed = True
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Local auth configuration initialized; existing non-placeholder secrets preserved.")


if __name__ == "__main__":
    main()
