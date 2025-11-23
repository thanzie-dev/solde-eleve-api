# import_excel.py
"""
Version PRO 5.0 (MODE STRICT) :

- Vérifie les doublons de NumRecu dans le fichier Excel AVANT l'import.
- Si doublons → génère doublons_recu.xlsx + log, et ANNULE l'import (rien en DB).
- Si aucun doublon → nettoyage automatique FIP / FF + import dans thz.db.
- Rapport général en fin d'import + détails dans import_log.txt.
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime

EXCEL_FILE = "THZBD2526GA.xlsx"
SHEET_NAME = 0
HEADER_ROW = 7           # ligne d'entête dans Excel (0-based pour pandas)
OUTPUT_DB = "thz.db"
LOG_FILE = "import_log.txt"
DUPLICATE_REPORT_FILE = "doublons_recu.xlsx"

# ----------------------------
#  COMPTEURS POUR LE RAPPORT FINAL
# ----------------------------
stats = {
    "corrections_fip": 0,
    "corrections_ff": 0,
    "corrections_autres": 0,
    "eleves_ajoutes": 0,
    "paiements_ajoutes": 0,
    "lignes_ignored": 0
}

# ----------------------------
#  DÉFINITION DES COLONNES
# ----------------------------
COLUMN_MAP = {
    "Matricule": ["Matricule", "MATRICULE"],
    "Nom": ["Nom", "Nom_Postnom", "Nom & Postnom", "Nom et Postnom", "Nom - Postnom"],
    "NumRecu": ["NumRecu", "N° Reçu", "N°Reçu", "No Recu", "NumeroRecu", "N° Recu"],
    "Sexe": ["Sexe"],
    "Classe": ["Classe"],
    "Categorie": ["Categorie", "Catégorie"],
    "Mois": ["Mois"],
    "FIP": ["FIP", "FI P", "Frais scolaire", "Frais Scolaire"],
    "FF": ["FF", "Frais de Fonctionnement"],
    "Obs": ["Obs", "Observation"],
    "Jour": ["Jour"],
    "DatePaiement": ["DatePaiement", "Date", "Date Paiement"],
    "AnneeScolaire": ["AnneeScolaire", "Année scolaire"],
    "Section": ["Section"],
    "Telephone": ["Telephone", "Téléphone"],
    "Email": ["Email", "Adresse Email"],
}

# ----------------------------
#  LOGGING
# ----------------------------

def init_log():
    """Réinitialise le fichier de log au début."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== Import du {datetime.now().isoformat()} ===\n")

def log_correction(message: str):
    """Affiche + enregistre un message, et met à jour les compteurs."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)

    msg = message.lower()
    if "fip" in msg:
        stats["corrections_fip"] += 1
    elif "ff" in msg:
        stats["corrections_ff"] += 1
    else:
        stats["corrections_autres"] += 1

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ----------------------------
#  UTILITAIRE : NUMÉRO DE REÇU
# ----------------------------

def normalize_receipt(value):
    """
    Normalise un numéro de reçu :
    - '8670.0'  -> '8670'
    - ' 8671 '  -> '8671'
    - 'ABC'     -> 'ABC' (si non numérique)
    """
    if value is None:
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
        else:
            return str(f)
    except Exception:
        return s

# ----------------------------
#  NETTOYAGE DES VALEURS NUMÉRIQUES
# ----------------------------

def to_float_safe(value, excel_line, column_name):
    """
    Convertit proprement en float :
    - supprime lettres/symboles parasites
    - log des corrections
    - retourne 0.0 en cas d'impossibilité
    """
    original = value

    if value is None:
        log_correction(f"Ligne Excel {excel_line} — {column_name} vide → 0")
        return 0.0

    value_str = str(value).strip()

    # Essai direct
    try:
        return float(value_str)
    except Exception:
        pass

    # Nettoyage : garder chiffres, ., , et -
    cleaned = "".join(c for c in value_str if c.isdigit() or c in [".", ",", "-"])
    cleaned = cleaned.replace(",", ".")

    if cleaned == "":
        log_correction(f"Ligne Excel {excel_line} — '{original}' invalide dans {column_name} → 0")
        return 0.0

    try:
        corrected = float(cleaned)
        log_correction(
            f"Ligne Excel {excel_line} — correction {column_name} : '{original}' → {corrected}"
        )
        return corrected
    except Exception:
        log_correction(
            f"Ligne Excel {excel_line} — impossible corriger '{original}' dans {column_name} → 0"
        )
        return 0.0

# ----------------------------
#  GESTION DES COLONNES
# ----------------------------

def find_column_name(df_columns, candidates):
    for c in candidates:
        for col in df_columns:
            if str(col).strip().lower() == str(c).strip().lower():
                return col
    return None

def normalize_columns(df):
    """
    Renomme les colonnes selon COLUMN_MAP
    et enlève les espaces autour des valeurs.
    """
    new_columns = {}
    for std_name, candidates in COLUMN_MAP.items():
        found = find_column_name(df.columns, candidates)
        if found:
            new_columns[found] = std_name
    df = df.rename(columns=new_columns)
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return df

# ----------------------------
#  VALIDATION DES DOUBLONS NumRecu (MODE STRICT)
# ----------------------------

def check_receipt_duplicates_in_excel(df):
    """
    MODE STRICT :
    - Vérifie les doublons de NumRecu dans le fichier Excel.
    - S'il y en a → génère doublons_recu.xlsx, log, message, et retourne False.
    - S'il n'y en a pas → retourne True.
    """
    if "NumRecu" not in df.columns:
        log_correction("⚠ Aucune colonne 'NumRecu' trouvée après normalisation.")
        # Sans NumRecu, difficile de contrôler : on continue mais c'est anormal.
        return True

    # Normalisation des reçus avant détection (ex. 8670.0 -> 8670)
    df["NumRecu"] = df["NumRecu"].apply(normalize_receipt)

    # Détection des doublons (lignes où NumRecu apparaît plus d'une fois)
    duplicated_mask = df.duplicated(subset=["NumRecu"], keep=False)
    duplicated_rows = df[duplicated_mask].copy()

    if duplicated_rows.empty:
        # Aucun doublon → OK
        return True

    # Ajouter l'index d'origine pour approximer le numéro de ligne dans Excel
    duplicated_rows = duplicated_rows.reset_index()  # 'index' = index pandas d'origine
    duplicated_rows.rename(columns={"index": "IndexDataFrame"}, inplace=True)
    duplicated_rows["LigneExcelApprox"] = duplicated_rows["IndexDataFrame"] + HEADER_ROW + 2

    # Colonnes utiles dans le rapport
    cols_report = ["NumRecu"]
    for c in ["Matricule", "Nom", "Mois", "FIP", "FF"]:
        if c in duplicated_rows.columns:
            cols_report.append(c)

    cols_final = ["LigneExcelApprox"] + cols_report
    report_df = duplicated_rows[cols_final]

    # Sauvegarde du rapport des doublons
    filename = DUPLICATE_REPORT_FILE
    try:
        report_df.to_excel(filename, index=False)
    except PermissionError:
        # Si le fichier est ouvert/verrouillé, on crée un fichier alternatif
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"doublons_recu_{suffix}.xlsx"
        report_df.to_excel(filename, index=False)
        log_correction(
            f"⚠ Le fichier '{DUPLICATE_REPORT_FILE}' était verrouillé. "
            f"Un rapport alternatif a été créé : '{filename}'."
        )

    nb_lignes = len(report_df)
    nb_recu_uniques = report_df["NumRecu"].nunique()

    log_correction(
        f"⛔ MODE STRICT : {nb_lignes} ligne(s) avec NumRecu dupliqué détectées "
        f"dans le fichier Excel, concernant {nb_recu_uniques} numéro(s) de reçu."
    )
    log_correction(
        f"Rapport des doublons généré dans le fichier '{filename}'."
    )

    print("\n================= IMPORT ANNULÉ (MODE STRICT) =================")
    print("Des doublons de numéros de reçu ont été détectés dans le fichier Excel.")
    print(f"Veuillez ouvrir le fichier '{filename}',")
    print("corriger les doublons directement dans l'Excel, puis relancer l'import.")
    print("AUCUNE donnée n'a été importée dans la base de données.")
    print("===============================================================\n")

    return False

# ----------------------------
#  BASE DE DONNÉES
# ----------------------------

def create_tables(conn):
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS eleves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        matricule TEXT UNIQUE,
        nom_postnom TEXT,
        sexe TEXT,
        classe TEXT,
        categorie TEXT,
        obs TEXT,
        telephone TEXT,
        email TEXT,
        section TEXT
    );

    CREATE TABLE IF NOT EXISTS paiements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        eleve_id INTEGER,
        recu_num TEXT UNIQUE,
        mois TEXT,
        fip REAL,
        ff REAL,
        jour TEXT,
        date_iso TEXT,
        annee_scolaire TEXT,
        FOREIGN KEY (eleve_id) REFERENCES eleves(id) ON DELETE CASCADE
    );
    """)
    conn.commit()

# ----------------------------
#  INSERTION DES DONNÉES
# ----------------------------

def insert_data(conn, df):
    cur = conn.cursor()

    # Récupérer les élèves existants
    cur.execute("SELECT matricule, id FROM eleves")
    existing_eleves = {row[0]: row[1] for row in cur.fetchall()}

    eleves_to_insert = []
    paiements_temp = []

    # Parcours des lignes (df déjà validé côté doublons NumRecu)
    for idx, row in df.iterrows():
        # Approximation de la ligne dans Excel
        excel_line = idx + HEADER_ROW + 2

        matricule = row.get("Matricule", "").strip()
        if not matricule:
            log_correction(f"Ligne Excel {excel_line} — Matricule manquant → ligne ignorée")
            stats["lignes_ignored"] += 1
            continue

        nom = row.get("Nom", "").strip()
        sexe = row.get("Sexe", "").strip()
        classe = row.get("Classe", "").strip()
        cat = row.get("Categorie", "").strip()
        obs = row.get("Obs", "").strip()
        tel = row.get("Telephone", "").strip()
        email = row.get("Email", "").strip()
        section = row.get("Section", "").strip()

        if matricule not in existing_eleves:
            eleves_to_insert.append((matricule, nom, sexe, classe, cat, obs, tel, email, section))
            stats["eleves_ajoutes"] += 1

        recu_raw = row.get("NumRecu", "").strip()
        recu = normalize_receipt(recu_raw)
        if not recu:
            log_correction(f"Ligne Excel {excel_line} — NumRecu manquant → paiement ignoré")
            stats["lignes_ignored"] += 1
            continue

        mois = row.get("Mois", "").strip()

        # Valeur FIP (nom normalisé ou ancien)
        if "FIP" in df.columns:
            fip_val = row.get("FIP")
        else:
            fip_val = row.get("FI P")

        fip = to_float_safe(fip_val, excel_line, "FIP")
        ff = to_float_safe(row.get("FF"), excel_line, "FF")

        jour = row.get("Jour", "").strip()
        date_iso = ""

        try:
            raw_date = row.get("DatePaiement")
            if pd.notna(raw_date):
                date_iso = pd.to_datetime(raw_date).isoformat()
        except Exception:
            log_correction(f"Ligne Excel {excel_line} — DatePaiement invalide → date ignorée")

        annee = row.get("AnneeScolaire", "").strip()

        paiements_temp.append((matricule, recu, mois, fip, ff, jour, date_iso, annee))

    # Insertion des élèves
    if eleves_to_insert:
        cur.executemany("""
            INSERT OR IGNORE INTO eleves
            (matricule, nom_postnom, sexe, classe, categorie, obs, telephone, email, section)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, eleves_to_insert)
        conn.commit()

    # Récupérer les élèves (avec IDs) après insertion
    cur.execute("SELECT matricule, id FROM eleves")
    existing_eleves = {row[0]: row[1] for row in cur.fetchall()}

    # Construction de la liste des paiements à insérer (avec eleve_id)
    paiements_final = []
    for matricule, recu, mois, fip, ff, jour, date_iso, annee in paiements_temp:
        eleve_id = existing_eleves.get(matricule)
        if eleve_id:
            paiements_final.append((eleve_id, recu, mois, fip, ff, jour, date_iso, annee))
        else:
            log_correction(
                f"Paiement reçu {recu} — élève inconnu : {matricule} → paiement ignoré"
            )
            stats["lignes_ignored"] += 1

    # Insertion des paiements avec sécurité doublon SQL (au cas où)
    for eleve_id, recu, mois, fip, ff, jour, date_iso, annee in paiements_final:
        try:
            cur.execute("""
                INSERT INTO paiements
                (eleve_id, recu_num, mois, fip, ff, jour, date_iso, annee_scolaire)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (eleve_id, recu, mois, fip, ff, jour, date_iso, annee))
            stats["paiements_ajoutes"] += 1
        except sqlite3.IntegrityError:
            # Doublon de recu_num en base (sécurité ultime)
            log_correction(
                f"DOUBLON SQL — le reçu '{recu}' existe déjà en base → paiement ignoré"
            )
            stats["lignes_ignored"] += 1

    conn.commit()

# ----------------------------
#  MAIN
# ----------------------------

def main():
    start = datetime.now()
    init_log()

    print(f"📘 Lecture du fichier : {EXCEL_FILE}")
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, header=HEADER_ROW, engine="openpyxl")

    # On limite aux colonnes utiles (comme dans ta version initiale)
    df = df.iloc[:, 2:18]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
    df = df.dropna(how="all")

    df = normalize_columns(df)

    print(f"🧩 Colonnes reconnues : {list(df.columns)}")
    print(f"📊 Lignes avant nettoyage : {len(df)}")

    # Suppression des lignes sans Matricule ou NumRecu (vides)
    if "Matricule" in df.columns:
        df = df[df["Matricule"].str.strip() != ""]
    else:
        log_correction("⚠ Aucune colonne 'Matricule' trouvée après normalisation.")

    if "NumRecu" in df.columns:
        df = df[df["NumRecu"].str.strip() != ""]
    else:
        log_correction("⚠ Aucune colonne 'NumRecu' trouvée après normalisation.")

    print(f"📊 Lignes après nettoyage : {len(df)}")

    # 🔴 Étape 1 : contrôle strict des doublons NumRecu dans l'Excel
    if not check_receipt_duplicates_in_excel(df):
        # Doublons trouvés → import annulé
        return

    # 🟢 Étape 2 : import propre (Excel garanti sans doublons de reçus)
    conn = sqlite3.connect(OUTPUT_DB)
    create_tables(conn)
    insert_data(conn, df)
    conn.close()

    end = datetime.now()
    duree = (end - start).total_seconds()

    # Rapport général
    print("\n===== RAPPORT GÉNÉRAL DE L’IMPORT =====")
    print(f"Élèves ajoutés : {stats['eleves_ajoutes']}")
    print(f"Paiements ajoutés : {stats['paiements_ajoutes']}")
    print(f"Corrections FIP : {stats['corrections_fip']}")
    print(f"Corrections FF : {stats['corrections_ff']}")
    print(f"Autres messages : {stats['corrections_autres']}")
    print(f"Lignes ignorées : {stats['lignes_ignored']}")
    print(f"Durée totale : {duree:.2f} sec")
    print("========================================\n")

    print(f"📄 Détails complets dans : {LOG_FILE}")

if __name__ == "__main__":
    main()
