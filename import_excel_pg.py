"""
import_excel_pg.py — VERSION SANS PANDAS (Python 3.13 compatible)

✔ Excel réel (openpyxl pur)
✔ En-têtes ligne 8
✔ Colonnes parasites ignorées
✔ Compatible Flask / CLI
✔ Fonctionne en local ET sur Render
"""

import os
import sys
import re
from datetime import datetime, date

import psycopg
from psycopg.rows import dict_row
from openpyxl import load_workbook

# ======================================================
# CONFIGURATION
# ======================================================

EXCEL_FILE = "THZBD2526GA.xlsx"
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL non définie")

HEADER_LINE = 8  # ligne Excel réelle (1-based)

REQUIRED_COLS = [
    "Matricule", "Nom", "Sexe", "Classe", "Categorie", "Section",
    "Telephone", "Email", "NumRecu", "Mois",
    "FIP", "FF", "Obs", "Jour", "DatePaiement", "AnneeScolaire"
]

# ======================================================
# UTILITAIRES
# ======================================================

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None

def to_float(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0

def parse_date(v):
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                pass
    return None

def matricule_valide(m):
    return bool(m and re.match(r"^(PL|LT)[0-9]+$", str(m).strip()))

# ======================================================
# LECTURE EXCEL (openpyxl PUR)
# ======================================================

def charger_excel():
    log("Lecture du fichier Excel (openpyxl)...")

    wb = load_workbook(EXCEL_FILE, data_only=True)
    ws = wb.active

    headers = []
    for cell in ws[HEADER_LINE]:
        if cell.value:
            headers.append(str(cell.value).strip())
        else:
            headers.append(None)

    col_index = {h: i for i, h in enumerate(headers) if h}

    missing = set(REQUIRED_COLS) - set(col_index.keys())
    if missing:
        raise RuntimeError(f"❌ Colonnes manquantes dans Excel : {missing}")

    lignes = []

    for row in ws.iter_rows(min_row=HEADER_LINE + 1, values_only=True):
        record = {col: clean_str(row[col_index[col]]) for col in REQUIRED_COLS}

        if not record["Matricule"] or not matricule_valide(record["Matricule"]):
            continue

        if not record["NumRecu"]:
            continue

        record["FIP"] = to_float(record["FIP"])
        record["FF"] = to_float(record["FF"])
        record["DatePaiement"] = parse_date(record["DatePaiement"])

        lignes.append(record)

    log(f"{len(lignes)} lignes valides prêtes à importer")
    return lignes

# ======================================================
# SCHEMA POSTGRESQL
# ======================================================

def creer_schema(conn):
    with conn.cursor() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS eleves (
            id SERIAL PRIMARY KEY,
            matricule TEXT UNIQUE,
            nom TEXT,
            sexe TEXT,
            classe TEXT,
            categorie TEXT,
            section TEXT,
            telephone TEXT,
            email TEXT
        );
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS paiements (
            id SERIAL PRIMARY KEY,
            eleve_id INTEGER REFERENCES eleves(id) ON DELETE CASCADE,
            numrecu TEXT UNIQUE,
            mois TEXT,
            fip NUMERIC,
            ff NUMERIC,
            obs TEXT,
            jour TEXT,
            datepaiement DATE,
            annee_scolaire TEXT
        );
        """)
    conn.commit()

# ======================================================
# INSERTION DONNÉES
# ======================================================

def inserer_donnees(lignes, conn):
    with conn.cursor() as c:

        for r in lignes:
            c.execute("""
            INSERT INTO eleves (
                matricule, nom, sexe, classe,
                categorie, section, telephone, email
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (matricule) DO UPDATE SET
                nom=EXCLUDED.nom,
                sexe=EXCLUDED.sexe,
                classe=EXCLUDED.classe,
                categorie=EXCLUDED.categorie,
                section=EXCLUDED.section,
                telephone=EXCLUDED.telephone,
                email=EXCLUDED.email;
            """, (
                r["Matricule"], r["Nom"], r["Sexe"], r["Classe"],
                r["Categorie"], r["Section"], r["Telephone"], r["Email"]
            ))

        for r in lignes:
            c.execute("""
            INSERT INTO paiements (
                eleve_id, numrecu, mois, fip, ff, obs,
                jour, datepaiement, annee_scolaire
            )
            SELECT id,%s,%s,%s,%s,%s,%s,%s,%s
            FROM eleves WHERE matricule=%s
            ON CONFLICT (numrecu) DO UPDATE SET
                mois=EXCLUDED.mois,
                fip=EXCLUDED.fip,
                ff=EXCLUDED.ff,
                obs=EXCLUDED.obs,
                jour=EXCLUDED.jour,
                datepaiement=EXCLUDED.datepaiement,
                annee_scolaire=EXCLUDED.annee_scolaire;
            """, (
                r["NumRecu"], r["Mois"], r["FIP"], r["FF"], r["Obs"],
                r["Jour"], r["DatePaiement"], r["AnneeScolaire"],
                r["Matricule"]
            ))

    conn.commit()

# ======================================================
# FONCTION PRINCIPALE
# ======================================================

def run_import():
    log("=== DÉBUT IMPORT POSTGRESQL ===")

    lignes = charger_excel()

    conn = psycopg.connect(
        DATABASE_URL,
        sslmode="require" if "render.com" in DATABASE_URL else "disable"
    )

    try:
        creer_schema(conn)
        inserer_donnees(lignes, conn)
    finally:
        conn.close()

    log("✅ IMPORT TERMINÉ AVEC SUCCÈS")

# ======================================================
# MODE TERMINAL
# ======================================================

if __name__ == "__main__":
    try:
        run_import()
    except Exception as e:
        log("❌ ERREUR IMPORT")
        print(e)
        sys.exit(1)
