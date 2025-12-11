"""
import_excel.py — Version PRO 7.0

Fonctionnalités :
- Détection automatique de la ligne d'en-tête (on ne dépend plus de header=7)
- Nettoyage et validation des données :
    * suppression lignes vides
    * suppression "TOTAL GENERAL" et lignes décoratives
    * un matricule valide = PLxxx ou LTxxx
    * NumRecu obligatoire et unique dans l'Excel
- Création / mise à jour des tables eleves et paiements dans thz.db
- Génération d'un rapport :
    * rapport_import.txt
    * rapport_import.pdf (avec logo si disponible)
"""

import os
import sys
import re
import sqlite3
from datetime import datetime

import pandas as pd
from dateutil import parser
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# =============================
#      CONFIGURATION
# =============================

DB_PATH = "thz.db"
EXCEL_FILE = "THZBD2526GA.xlsx"

RAPPORT_TXT = "rapport_import.txt"
RAPPORT_PDF = "rapport_import.pdf"

# Mets ton logo dans le même dossier que ce script
# et adapte le nom si nécessaire :
LOGO_PATH = "logo_cs_nst.png"   # par ex. ton logo C.S.NST


# =============================
#      UTILITAIRES GÉNÉRAUX
# =============================

def log(msg: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


def clean_str(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    return s


def to_float(val) -> float:
    if pd.isna(val):
        return 0.0
    s = str(val).replace(",", ".").strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(val):
    s = clean_str(val)
    if not s:
        return None
    try:
        dt = parser.parse(s, dayfirst=True)
        return dt.date().isoformat()
    except Exception:
        return s


def normalize_annee_scolaire(v):
    s = clean_str(v)
    if not s:
        return None
    s = s.replace(" ", "")
    # ex : 25-26 -> 2025-2026
    if len(s) == 5 and s[2] == "-":
        try:
            d = int(s[:2])
            f = int(s[3:])
            return f"20{d:02d}-20{f:02d}"
        except Exception:
            return s
    return s


def normalize_key(label: str) -> str:
    """Normalise un texte pour comparer les entêtes."""
    if label is None:
        return ""
    cleaned = "".join(ch for ch in str(label) if ch.isalnum())
    return cleaned.lower()


def matricule_valide(m: str) -> bool:
    """Matricule valide : commence par PL ou LT suivi de chiffres."""
    if m is None:
        return False
    return bool(re.match(r"^(PL|LT)[0-9]+$", m))


# =============================
#   1. LECTURE + DÉTECTION HEADER
# =============================

def detecter_ligne_entete(df_raw: pd.DataFrame) -> int:
    """
    Cherche la ligne qui contient les vrais titres :
    Matricule, Nom, NumRecu, etc.
    On scanne les ~30 premières lignes.
    """
    target_keys = {"matricule", "nom", "numrecu"}

    max_lignes = min(30, len(df_raw))
    for i in range(max_lignes):
        row = df_raw.iloc[i].tolist()
        norms = {normalize_key(v) for v in row}
        if target_keys.issubset(norms):
            return i

    raise RuntimeError(
        "Impossible de détecter la ligne d'en-tête (Matricule/Nom/NumRecu). "
        "Vérifie la structure du fichier Excel."
    )


def charger_excel(path: str):
    """
    - Lit tout le fichier sans entête (header=None)
    - Détecte automatiquement la ligne d'entête
    - Renomme les colonnes selon notre schéma
    - Retourne un DataFrame avec uniquement les colonnes utiles
    et un dict de statistiques.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Fichier Excel introuvable : {path}")

    log(f"Lecture brute du fichier Excel : {path} (sans entête)...")
    df_raw = pd.read_excel(path, engine="openpyxl", header=None, dtype=object)
    lignes_brutes = len(df_raw)

    header_row = detecter_ligne_entete(df_raw)
    log(f"Ligne d'entête détectée automatiquement : {header_row + 1} (Excel)")

    # Ligne d'entête
    header_vals = df_raw.iloc[header_row].tolist()

    # Data en-dessous
    df_data = df_raw.iloc[header_row + 1 :].reset_index(drop=True)

    # Mapping des noms normalisés -> canonique
    canon_map = {
        "matricule": "Matricule",
        "nom": "Nom",
        "numrecu": "NumRecu",
        "sexe": "Sexe",
        "classe": "Classe",
        "categorie": "Categorie",
        "mois": "Mois",
        "fip": "FIP",
        "ff": "FF",
        "obs": "Obs",
        "jour": "Jour",
        "datepaiement": "DatePaiement",
        "anneescolaire": "AnneeScolaire",
        "section": "Section",
        "telephone": "Telephone",
        "email": "Email",
    }

    rename_map = {}
    for idx, val in enumerate(header_vals):
        norm = normalize_key(val)
        if norm in canon_map:
            rename_map[idx] = canon_map[norm]

    df_data = df_data.rename(columns=rename_map)

    expected = list(canon_map.values())
    missing = [c for c in expected if c not in df_data.columns]
    if missing:
        raise KeyError(
            "Colonnes manquantes après détection d'entête : " + ", ".join(missing)
        )

    df = df_data[expected]

    stats = {
        "lignes_brutes": lignes_brutes,
        "ligne_entete_excel": header_row + 1,
    }
    return df, stats


# =============================
#  2. NETTOYAGE / VALIDATION
# =============================

def preparer_dataframe(df: pd.DataFrame):
    stats = {}

    # Nettoyage texte
    text_cols = [
        "Matricule", "Nom", "NumRecu", "Sexe", "Classe", "Categorie",
        "Mois", "Obs", "Jour", "Section", "Telephone", "Email"
    ]
    for col in text_cols:
        df[col] = df[col].apply(clean_str)

    # Montants
    df["FIP"] = df["FIP"].apply(to_float)
    df["FF"] = df["FF"].apply(to_float)

    # Dates
    df["DatePaiement"] = df["DatePaiement"].apply(parse_date)
    df["AnneeScolaire"] = df["AnneeScolaire"].apply(normalize_annee_scolaire)

    # Lignes totalement vides
    before = len(df)
    text_and_num = text_cols + ["FIP", "FF", "DatePaiement", "AnneeScolaire"]
    empty_mask = df[text_and_num].isna().all(axis=1)
    df = df[~empty_mask]
    nb_vides = int(empty_mask.sum())
    log(f"Lignes totalement vides supprimées : {nb_vides}")
    stats["lignes_vides_supprimees"] = nb_vides

    # Lignes dont le matricule n'est pas un vrai matricule
    before2 = len(df)
    df = df[df["Matricule"].apply(matricule_valide)]
    nb_invalide = before2 - len(df)
    log(f"Lignes supprimées (matricule invalide / décorations / TOTAL GENERAL) : {nb_invalide}")
    stats["lignes_matricule_invalide"] = nb_invalide

    # Validation NumRecu non vide
    if df["NumRecu"].isna().any():
        bad = df[df["NumRecu"].isna()]
        log("❌ Lignes avec NumRecu vide :")
        print(bad[["Matricule", "Nom", "Mois", "FIP"]].head(20))
        raise ValueError("ERREUR : NumRecu vide détecté → import stoppé.")

    # Doublons NumRecu
    dups = df[df.duplicated("NumRecu", keep=False)]
    if not dups.empty:
        log("❌ Doublons NumRecu dans l'Excel :")
        print(dups[["Matricule", "Nom", "NumRecu"]])
        raise ValueError("ERREUR : NumRecu dupliqué dans l'Excel → corrige le fichier.")

    stats["lignes_apres_nettoyage"] = len(df)
    log("Données nettoyées et validées.")
    return df, stats


# =============================
#  3. SCHEMA SQLITE
# =============================

def creer_schema(conn: sqlite3.Connection):
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS eleves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eleve_id INTEGER,
            matricule TEXT,
            numrecu TEXT UNIQUE,
            mois TEXT,
            fip REAL,
            ff REAL,
            obs TEXT,
            jour TEXT,
            datepaiement TEXT,
            annee_scolaire TEXT,
            FOREIGN KEY (eleve_id) REFERENCES eleves(id)
        );
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_eleves_matricule ON eleves(matricule);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paiements_matricule ON paiements(matricule);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paiements_numrecu ON paiements(numrecu);")

    conn.commit()


# =============================
#  4. INSERTION / MISE À JOUR
# =============================

def inserer_donnees(df: pd.DataFrame, conn: sqlite3.Connection):
    c = conn.cursor()

    c.execute("SELECT id, matricule FROM eleves;")
    exist_eleves = {m: i for i, m in c.fetchall()}

    c.execute("SELECT id, numrecu FROM paiements;")
    exist_pay = {nr: i for i, nr in c.fetchall()}

    ins_e = maj_e = ins_p = maj_p = 0

    for _, row in df.iterrows():
        mat = row["Matricule"]
        nom = row["Nom"]
        nr = row["NumRecu"]

        # Élève
        if mat not in exist_eleves:
            c.execute("""
                INSERT INTO eleves (matricule, nom, sexe, classe, categorie,
                                    section, telephone, email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mat, nom, row["Sexe"], row["Classe"], row["Categorie"],
                row["Section"], row["Telephone"], row["Email"]
            ))
            eleve_id = c.lastrowid
            exist_eleves[mat] = eleve_id
            ins_e += 1
        else:
            eleve_id = exist_eleves[mat]
            c.execute("""
                UPDATE eleves SET
                    nom = COALESCE(NULLIF(?,''), nom),
                    sexe = COALESCE(NULLIF(?,''), sexe),
                    classe = COALESCE(NULLIF(?,''), classe),
                    categorie = COALESCE(NULLIF(?,''), categorie),
                    section = COALESCE(NULLIF(?,''), section),
                    telephone = COALESCE(NULLIF(?,''), telephone),
                    email = COALESCE(NULLIF(?,''), email)
                WHERE matricule = ?
            """, (
                nom or "", row["Sexe"] or "", row["Classe"] or "",
                row["Categorie"] or "", row["Section"] or "",
                row["Telephone"] or "", row["Email"] or "", mat
            ))
            maj_e += 1

        # Paiement
        if nr in exist_pay:
            c.execute("""
                UPDATE paiements SET
                    eleve_id=?, matricule=?, mois=?, fip=?, ff=?, obs=?,
                    jour=?, datepaiement=?, annee_scolaire=?
                WHERE numrecu=?
            """, (
                eleve_id, mat, row["Mois"], row["FIP"], row["FF"],
                row["Obs"], row["Jour"], row["DatePaiement"],
                row["AnneeScolaire"], nr
            ))
            maj_p += 1
        else:
            c.execute("""
                INSERT INTO paiements (
                    eleve_id, matricule, numrecu, mois, fip, ff, obs,
                    jour, datepaiement, annee_scolaire
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                eleve_id, mat, nr, row["Mois"], row["FIP"], row["FF"],
                row["Obs"], row["Jour"], row["DatePaiement"],
                row["AnneeScolaire"]
            ))
            exist_pay[nr] = c.lastrowid
            ins_p += 1

    conn.commit()
    return {
        "eleves_inseres": ins_e,
        "eleves_maj": maj_e,
        "paiements_inseres": ins_p,
        "paiements_maj": maj_p,
    }


# =============================
#  5. RAPPORT TXT & PDF
# =============================

def generer_rapport_txt(stats: dict, path: str):
    lines = []
    lines.append("=== RAPPORT D'IMPORT EXCEL -> SQLITE ===")
    lines.append(f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"Fichier Excel : {EXCEL_FILE}")
    lines.append(f"Base SQLite  : {os.path.abspath(DB_PATH)}")
    lines.append("")
    lines.append(f"Lignes brutes Excel : {stats.get('lignes_brutes')}")
    lines.append(f"Ligne d'entête détectée : {stats.get('ligne_entete_excel')}")
    lines.append(f"Lignes vides supprimées : {stats.get('lignes_vides_supprimees')}")
    lines.append(f"Lignes matricule invalide supprimées : {stats.get('lignes_matricule_invalide')}")
    lines.append(f"Lignes après nettoyage : {stats.get('lignes_apres_nettoyage')}")
    lines.append("")
    lines.append(f"Élèves insérés : {stats.get('eleves_inseres')}")
    lines.append(f"Élèves mis à jour : {stats.get('eleves_maj')}")
    lines.append(f"Paiements insérés : {stats.get('paiements_inseres')}")
    lines.append(f"Paiements mis à jour : {stats.get('paiements_maj')}")
    lines.append("")
    lines.append(f"Durée totale : {stats.get('duree')}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def generer_rapport_pdf(stats: dict, path: str):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    y = height - 50

    # Logo si disponible
    if os.path.exists(LOGO_PATH):
        try:
            c.drawImage(LOGO_PATH, 40, height - 140, width=120, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 16)
    c.drawString(180, height - 80, "RAPPORT D'IMPORT EXCEL → SQLITE")

    c.setFont("Helvetica", 10)
    y = height - 140
    lignes = [
        f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Fichier Excel : {EXCEL_FILE}",
        f"Base SQLite : {os.path.abspath(DB_PATH)}",
        "",
        f"Lignes brutes Excel : {stats.get('lignes_brutes')}",
        f"Ligne d'entête détectée : {stats.get('ligne_entete_excel')}",
        f"Lignes vides supprimées : {stats.get('lignes_vides_supprimees')}",
        f"Lignes matricule invalide supprimées : {stats.get('lignes_matricule_invalide')}",
        f"Lignes après nettoyage : {stats.get('lignes_apres_nettoyage')}",
        "",
        f"Élèves insérés : {stats.get('eleves_inseres')}",
        f"Élèves mis à jour : {stats.get('eleves_maj')}",
        f"Paiements insérés : {stats.get('paiements_inseres')}",
        f"Paiements mis à jour : {stats.get('paiements_maj')}",
        "",
        f"Durée totale : {stats.get('duree')}",
    ]

    for line in lignes:
        c.drawString(40, y, line)
        y -= 15

    c.showPage()
    c.save()


# =============================
#  6. FONCTION D'IMPORT GLOBALE (POUR FLASK + CLI)
# =============================

def run_import():
    """
    Fonction principale réutilisable :
    - utilisée par Flask (import_excel.run_import())
    - utilisée par le main() ci-dessous (mode terminal)
    Lève les exceptions en cas d'erreur.
    """
    debut = datetime.now()
    log("=== Début de l'import Excel ===")

    stats = {}

    # 1) Chargement Excel
    df, s1 = charger_excel(EXCEL_FILE)
    stats.update(s1)

    # 2) Nettoyage / validation
    df, s2 = preparer_dataframe(df)
    stats.update(s2)

    # 3) Création / mise à jour DB
    conn = sqlite3.connect(DB_PATH)
    creer_schema(conn)
    s3 = inserer_donnees(df, conn)
    conn.close()
    stats.update(s3)

    # 4) Durée
    stats["duree"] = str(datetime.now() - debut)

    # 5) Rapports
    generer_rapport_txt(stats, RAPPORT_TXT)
    generer_rapport_pdf(stats, RAPPORT_PDF)

    log("✅ Import terminé avec succès.")
    log(f"Rapport TXT : {os.path.abspath(RAPPORT_TXT)}")
    log(f"Rapport PDF : {os.path.abspath(RAPPORT_PDF)}")

    return stats


# =============================
#  7. PROGRAMME PRINCIPAL (CLI)
# =============================

def main():
    try:
        run_import()
    except Exception as e:
        log("❌ Import interrompu.")
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
