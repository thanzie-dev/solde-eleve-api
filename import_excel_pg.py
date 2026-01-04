"""
import_excel_pg.py — Version PRO PostgreSQL STABLE 1.1

✔ Import Excel → PostgreSQL (Render)
✔ Aucune dépendance psycopg2.extras
✔ Compatible Flask (importé sans crash)
✔ Simple, lisible, durable
"""

import os
import sys
import re
from datetime import datetime

import pandas as pd
from dateutil import parser
import psycopg2

# ======================================================
# CONFIGURATION
# ======================================================

EXCEL_FILE = "THZBD2526GA.xlsx"
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL non définie")

# ======================================================
# UTILITAIRES
# ======================================================

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def clean_str(v):
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None

def to_float(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0

def parse_date(v):
    if not v:
        return None
    try:
        return parser.parse(str(v), dayfirst=True).date()
    except Exception:
        return None

def matricule_valide(m):
    return bool(m and re.match(r"^(PL|LT)[0-9]+$", m))

def execute_many(cursor, query, data):
    for row in data:
        cursor.execute(query, row)

# ======================================================
# LECTURE EXCEL
# ======================================================

def charger_excel():
    df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=object)

    df = df.rename(columns=lambda c: str(c).strip())

    cols = [
        "Matricule", "Nom", "Sexe", "Classe", "Categorie",
        "Section", "Telephone", "Email",
        "NumRecu", "Mois", "FIP", "FF",
        "Obs", "Jour", "DatePaiement", "AnneeScolaire"
    ]

    df = df[cols]

    df["Matricule"] = df["Matricule"].apply(clean_str)
    df = df[df["Matricule"].apply(matricule_valide)]

    df["Nom"] = df["Nom"].apply(clean_str)
    df["Sexe"] = df["Sexe"].apply(clean_str)
    df["Classe"] = df["Classe"].apply(clean_str)
    df["Categorie"] = df["Categorie"].apply(clean_str)
    df["Section"] = df["Section"].apply(clean_str)
    df["Telephone"] = df["Telephone"].apply(clean_str)
    df["Email"] = df["Email"].apply(clean_str)

    df["NumRecu"] = df["NumRecu"].apply(clean_str)
    if df["NumRecu"].isna().any():
        raise ValueError("❌ NumRecu vide détecté")

    if df["NumRecu"].duplicated().any():
        raise ValueError("❌ NumRecu dupliqué dans Excel")

    df["FIP"] = df["FIP"].apply(to_float)
    df["FF"] = df["FF"].apply(to_float)
    df["DatePaiement"] = df["DatePaiement"].apply(parse_date)

    log(f"{len(df)} lignes valides prêtes à importer")
    return df

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
            eleve_id INTEGER REFERENCES eleves(id),
            matricule TEXT,
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

def inserer_donnees(df, conn):
    with conn.cursor() as c:

        # ---------- ÉLÈVES ----------
        eleves_data = [
            (
                r.Matricule, r.Nom, r.Sexe, r.Classe,
                r.Categorie, r.Section, r.Telephone, r.Email
            )
            for r in df.itertuples()
        ]

        execute_many(c, """
        INSERT INTO eleves (matricule, nom, sexe, classe, categorie, section, telephone, email)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (matricule) DO UPDATE SET
            nom=EXCLUDED.nom,
            sexe=EXCLUDED.sexe,
            classe=EXCLUDED.classe,
            categorie=EXCLUDED.categorie,
            section=EXCLUDED.section,
            telephone=EXCLUDED.telephone,
            email=EXCLUDED.email;
        """, eleves_data)

        # ---------- PAIEMENTS ----------
        paiements_data = [
            (
                r.Matricule, r.NumRecu, r.Mois, r.FIP, r.FF,
                r.Obs, r.Jour, r.DatePaiement, r.AnneeScolaire
            )
            for r in df.itertuples()
        ]

        execute_many(c, """
        INSERT INTO paiements (
            eleve_id, matricule, numrecu, mois, fip, ff, obs,
            jour, datepaiement, annee_scolaire
        )
        SELECT e.id,%s,%s,%s,%s,%s,%s,%s,%s,%s
        FROM eleves e
        WHERE e.matricule=%s
        ON CONFLICT (numrecu) DO UPDATE SET
            mois=EXCLUDED.mois,
            fip=EXCLUDED.fip,
            ff=EXCLUDED.ff,
            obs=EXCLUDED.obs,
            jour=EXCLUDED.jour,
            datepaiement=EXCLUDED.datepaiement,
            annee_scolaire=EXCLUDED.annee_scolaire;
        """, [(*p, p[0]) for p in paiements_data])

    conn.commit()

# ======================================================
# FONCTION PRINCIPALE (FLASK + CLI)
# ======================================================

def run_import():
    log("=== DÉBUT IMPORT POSTGRESQL ===")

    df = charger_excel()

    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    creer_schema(conn)
    inserer_donnees(df, conn)
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
