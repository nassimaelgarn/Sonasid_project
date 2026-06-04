from __future__ import annotations

from pathlib import Path


def main() -> None:
    try:
        from openpyxl import Workbook
    except Exception as e:
        raise SystemExit(f"openpyxl is required to generate the template: {e}")

    wb = Workbook()
    ws = wb.active
    ws.title = "users"

    # One sheet supports:
    # - SSO mapping: email + role (+ enabled)
    # - Local code login: username + code + role (+ display_name/email/enabled)
    ws.append(["username", "code", "display_name", "email", "role", "enabled"])
    ws.append(["abdelkaioume.ammour", "Am1122", "Abdelkaioume Ammour", "ammour@company.com", "analyst_2025_2026", 1])
    ws.append(["adil.jiri", "AdiL1122", "Adil Jiri", "", "analyst_2025_2026", 1])
    ws.append(["nassima.elgarn", "Na1122", "Nassima EL GARN", "nassima.elgarn@uir.ac.ma", "analyst_2026", 1])
    ws.append(["admin", "Ad1122", "Admin", "admin@company.com", "admin", 1])

    out = Path(__file__).with_name("users.xlsx")
    wb.save(out)
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()

