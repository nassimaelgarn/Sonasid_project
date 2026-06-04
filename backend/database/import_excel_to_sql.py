import pandas as pd
from sqlalchemy import create_engine
import os
import unicodedata

def clean_name(name):
    name = name.replace(" ", "_").replace("-", "_")
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode()
    return name

# Chemin racine du projet
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Chemins corrects
file = os.path.join(BASE_DIR, "data", "DATA-ACIERIE.xlsx")
db_path = os.path.join(BASE_DIR, "db", "sonasid.db")

engine = create_engine(f"sqlite:///{db_path}")

xls = pd.ExcelFile(file)

ignore = [
    "Dictionnaire de données",
    "Tolérances Analyses",
    "Schéma Relationnel"
]

for sheet in xls.sheet_names:
    if sheet not in ignore:

        df = pd.read_excel(file, sheet_name=sheet)

        table_name = clean_name(sheet)
        df.to_sql(
            table_name,
            engine,
            if_exists="replace",
            index=False
        )

print("✅ All tables imported into SQLite successfully")