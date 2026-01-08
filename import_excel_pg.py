"""
import_excel_pg.py — Version PRO PostgreSQL STABLE 1.3

✔ Excel réel (colonnes parasites ignorées)
✔ En-têtes ligne 8
✔ Mapping robuste par nom
✔ Compatible Flask / CLI
✔ Prêt production
"""

import os
import sys
import re
from datetime import datetime

import pandas as pd
from dateutil import parser
import psycopg
from psycopg.rows import dict_row


# ======================================================
# CONFIGURATION
# ======================================================

EXCEL_FILE = "THZBD2526GA.xlsx"
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL non définie")

HEADER_LINE = 7  # entêtes Excel à la ligne 8

# Colonnes attendues (mapping réel Excel)
REQUIRED_COLS = {
    "Matricule": "Matricule",
    "Nom": "Nom",
    "Sexe": "Sexe",
    "Classe": "Classe",
    "Categorie": "Categorie",
    "Section": "Section",
    "Telephone": "Telephone",
    "Email": "Email",
    "NumRecu": "NumRecu",
    "Mois": "Mois",
    "FIP": "FIP",
    "FF": "FF",
    "Obs": "Obs",
    "Jour": "Jour",
    "DatePaiement": "DatePaiement",
    "AnneeScolaire": "AnneeScolaire",
}

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

from datetime import datetime, date

def parse_date(v):
    if v is None:
        return None

    # Déjà une date ou datetime
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()

    # Chaîne de caractères
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue

    return None



def matricule_valide(m):
    return bool(m and re.match(r"^(PL|LT)[0-9]+$", str(m).strip()))

# ======================================================
# LECTURE EXCEL (ROBUSTE)
# ======================================================
def charger_excel():
    log("Lecture du fichier Excel...")

    df = pd.read_excel(
        EXCEL_FILE,
        header=HEADER_LINE,
        engine="openpyxl",
        dtype=object
    )

    # Nettoyage noms colonnes
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", "", regex=False)
        .str.replace("\r", "", regex=False)
    )

    # Suppression colonnes parasites Unnamed
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    # Vérification colonnes requises
    missing = set(REQUIRED_COLS.keys()) - set(df.columns)
    if missing:
        raise ValueError(f"❌ Colonnes manquantes dans Excel : {missing}")

    # Sélection propre
    df = df[list(REQUIRED_COLS.keys())]

    # Nettoyage données élèves
    df["Matricule"] = df["Matricule"].apply(clean_str)
    df = df[df["Matricule"].notna()]
    df = df[df["Matricule"].apply(matricule_valide)]

    for col in ["Nom", "Sexe", "Classe", "Categorie", "Section", "Telephone", "Email"]:
        df[col] = df[col].apply(clean_str)

    # Paiements
    df["NumRecu"] = df["NumRecu"].apply(clean_str)
    df = df[df["NumRecu"].notna()]
    df = df.drop_duplicates(subset=["NumRecu"])

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

def inserer_donnees(df, conn):
    with conn.cursor() as c:

        # ÉLÈVES
        for r in df.itertuples():
            c.execute("""
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
            """, (
                r.Matricule, r.Nom, r.Sexe, r.Classe,
                r.Categorie, r.Section, r.Telephone, r.Email
            ))

        # PAIEMENTS
        for r in df.itertuples():
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
                r.NumRecu, r.Mois, r.FIP, r.FF, r.Obs,
                r.Jour, r.DatePaiement, r.AnneeScolaire,
                r.Matricule
            ))

    conn.commit()

# ======================================================
# FONCTION PRINCIPALE
# ======================================================

import psycopg
from psycopg.rows import dict_row

def run_import():
    log("=== DÉBUT IMPORT POSTGRESQL ===")

    df = charger_excel()

    conn = psycopg.connect(
        DATABASE_URL,
        sslmode="require" if "render.com" in DATABASE_URL else "disable"
    )

    try:
        creer_schema(conn)
        inserer_donnees(df, conn)
        conn.commit()
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
