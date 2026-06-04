#!/usr/bin/env python3
"""Affiche l'IP publique à ajouter au pare-feu Azure SQL Sonasid."""

from __future__ import annotations

import json
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=10) as resp:
            data = json.loads(resp.read().decode())
        ip = data.get("ip", "?")
    except Exception as e:
        print("Impossible de détecter l'IP publique:", e)
        return 1

    print("IP publique actuelle (à autoriser sur Azure SQL) :", ip)
    print()
    print("Portail Azure :")
    print("  SQL Server → sql-son-prd → Mise en réseau → Règles de pare-feu")
    print(f"  Nom : dev-{ip.replace('.', '-')}  |  IP : {ip}  |  Plage : {ip}")
    print()
    print("PowerShell / Azure CLI (exemple) :")
    print(
        f"  az sql server firewall-rule create "
        f"-g <resource-group> -s sql-son-prd "
        f"-n allow-{ip.replace('.', '-')} "
        f"--start-ip-address {ip} --end-ip-address {ip}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
