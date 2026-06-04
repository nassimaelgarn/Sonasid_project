-- =============================================================================
-- Tests KPI Sonasid — Azure Data Studio (son-db-prd)
-- Remplacez @Fournisseur / @Navire_Id par des IDs trouvés ci-dessous.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0) Découverte : quels IDs ont vraiment des données ?
-- -----------------------------------------------------------------------------

-- Fournisseurs avec au moins un arrivage
SELECT a.Arrivage_FournisseurId AS FournisseurId,
       f.Fournisseur_Nom,
       COUNT(*) AS nombre_arrivages,
       SUM(a.Arrivage_TonnageTotal) AS tonnage_importe_total
FROM dbo.ARRIVAGE a
LEFT JOIN dbo.FOURNISSEUR f ON a.Arrivage_FournisseurId = f.Fournisseur_Id
GROUP BY a.Arrivage_FournisseurId, f.Fournisseur_Nom
ORDER BY nombre_arrivages DESC;

-- Navires avec transferts (tonnage transféré)
SELECT nv.Navire_Id,
       nv.Navire_Nom,
       nv.Navire_Active,
       COUNT(*) AS nb_lignes_transfert,
       SUM(t.Transfert_PoidsNet) AS tonnage_transfere_total
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
GROUP BY nv.Navire_Id, nv.Navire_Nom, nv.Navire_Active
ORDER BY nb_lignes_transfert DESC;

-- Navires actifs (KPI global)
SELECT COUNT(*) AS nombre_navires_actifs
FROM dbo.NAVIRE
WHERE Navire_Active = 1;

-- Navires en déchargement (début réel renseigné, fin non clôturée)
SELECT COUNT(DISTINCT nv.Navire_Id) AS nombre_navires_en_dechargement
FROM dbo.ARRIVAGE a
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL;

-- Détail (liste POC chatbot)
SELECT nv.Navire_Nom,
       a.Arrivage_Id,
       a.Arrivage_DateDebutReelleDechargement,
       a.Arrivage_TonnageTotal,
       sd.quantite_restante
FROM dbo.ARRIVAGE a
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
OUTER APPLY (
    SELECT TOP 1 s.SuiviDechargement_QuantiteRestante AS quantite_restante
    FROM dbo.SUIVI_DECHARGEMENT s
    WHERE s.SuiviDechargement_ArrivageId = a.Arrivage_Id
    ORDER BY s.SuiviDechargement_Id DESC
) sd
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL
ORDER BY nv.Navire_Nom;

-- Tonnage déchargé (cumul shifts, arrivages en cours)
SELECT SUM(s.SuiviDechargement_QuantiteDecharge) AS tonnage_decharge
FROM dbo.SUIVI_DECHARGEMENT s
INNER JOIN dbo.ARRIVAGE a ON s.SuiviDechargement_ArrivageId = a.Arrivage_Id
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL;

-- Tonnage restant (dernier shift)
SELECT SUM(sd.quantite_restante) AS tonnage_restant
FROM dbo.ARRIVAGE a
OUTER APPLY (
    SELECT TOP 1 s.SuiviDechargement_QuantiteRestante AS quantite_restante
    FROM dbo.SUIVI_DECHARGEMENT s
    WHERE s.SuiviDechargement_ArrivageId = a.Arrivage_Id
    ORDER BY s.SuiviDechargement_Id DESC
) sd
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL;

-- Taux de déchargement moyen (t/j contractuel sur ARRIVAGE)
SELECT AVG(a.Arrivage_TauxDechargement) AS taux_dechargement_moyen
FROM dbo.ARRIVAGE a
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Exemples d’IDs avec données (juin 2026 — à revérifier après requête 0)
-- Fournisseur : 40 (23 arrivages), 89 (7), 110 (6), 113 (6), 39 (6)
-- Navire      : 79 CAPE DOUAKTO, 76 CHARLIE, 85 LENA, 72, 45, 32…
-- -----------------------------------------------------------------------------

DECLARE @Fournisseur INT = 40;   -- changer après SELECT fournisseurs
DECLARE @Navire_Id   INT = 79;   -- changer après SELECT navires

-- -----------------------------------------------------------------------------
-- Qualités (référentiel & tonnages commande / transfert)
-- -----------------------------------------------------------------------------
SELECT TOP 30 q.Qualite_Id, q.Qualite_Libelle, q.Qualite_Active
FROM dbo.QUALITE q
WHERE q.Qualite_Active = 1
ORDER BY q.Qualite_Libelle;

SELECT c.Commande_QualiteId, q.Qualite_Libelle, SUM(c.Commande_Tonnage) AS tonnage
FROM dbo.COMMANDE c
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
WHERE a.Arrivage_DateCreation >= '2026-01-01' AND a.Arrivage_DateCreation < '2027-01-01'
GROUP BY c.Commande_QualiteId, q.Qualite_Libelle
ORDER BY tonnage DESC;

SELECT c.Commande_QualiteId, q.Qualite_Libelle, SUM(t.Transfert_PoidsNet) AS tonnage_transfere
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
WHERE a.Arrivage_DateCreation >= '2026-01-01' AND a.Arrivage_DateCreation < '2027-01-01'
GROUP BY c.Commande_QualiteId, q.Qualite_Libelle
ORDER BY tonnage_transfere DESC;

-- -----------------------------------------------------------------------------
-- 1) Nombre des arrivages (total)
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS nombre_arrivages
FROM dbo.ARRIVAGE;

-- -----------------------------------------------------------------------------
-- 2) Nombre des arrivages par fournisseur
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS nombre_arrivages
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = @Fournisseur;

-- Variante id explicite (ex. 40)
SELECT COUNT(*) AS nombre_arrivages
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = 40;

-- -----------------------------------------------------------------------------
-- 3) Tonnage importé par fournisseur
-- -----------------------------------------------------------------------------
SELECT SUM(Arrivage_TonnageTotal) AS tonnage_importe
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = @Fournisseur;

SELECT SUM(Arrivage_TonnageTotal) AS tonnage_importe
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = 40;

-- -----------------------------------------------------------------------------
-- 4) Tonnage par qualité par fournisseur
-- (GROUP BY sans Commande_Tonnage — agrégation correcte)
-- -----------------------------------------------------------------------------
SELECT c.Commande_QualiteId,
       q.Qualite_Libelle,
       SUM(c.Commande_Tonnage) AS tonnage
FROM dbo.COMMANDE c
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
WHERE a.Arrivage_FournisseurId = @Fournisseur
GROUP BY c.Commande_QualiteId, q.Qualite_Libelle
ORDER BY q.Qualite_Libelle;

-- -----------------------------------------------------------------------------
-- 5) Tonnage transféré par qualité (détail — une ligne par transfert)
-- -----------------------------------------------------------------------------
SELECT TOP 50
       q.Qualite_Libelle,
       c.Commande_QualiteId,
       t.Transfert_PoidsNet
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
ORDER BY t.Transfert_Id;

-- Comptage / somme globale (contrôle chatbot)
SELECT COUNT(*) AS nb_transferts,
       SUM(t.Transfert_PoidsNet) AS tonnage_transfere_total
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id;

-- -----------------------------------------------------------------------------
-- 6) Tonnage transféré par qualité par navire
-- -----------------------------------------------------------------------------
SELECT a.Arrivage_Id,
       nv.Navire_Nom,
       c.Commande_QualiteId,
       q.Qualite_Libelle,
       SUM(t.Transfert_PoidsNet) AS tonnage_transfere
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
WHERE nv.Navire_Id = @Navire_Id
GROUP BY a.Arrivage_Id, nv.Navire_Nom, c.Commande_QualiteId, q.Qualite_Libelle
ORDER BY a.Arrivage_Id, q.Qualite_Libelle;

-- Variante navire 79
SELECT a.Arrivage_Id,
       nv.Navire_Nom,
       c.Commande_QualiteId,
       q.Qualite_Libelle,
       SUM(t.Transfert_PoidsNet) AS tonnage_transfere
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
WHERE nv.Navire_Id = 79
GROUP BY a.Arrivage_Id, nv.Navire_Nom, c.Commande_QualiteId, q.Qualite_Libelle;

-- -----------------------------------------------------------------------------
-- Bonus : arrivages par année (filtre chat optionnel)
-- -----------------------------------------------------------------------------
SELECT YEAR(Arrivage_DateCreation) AS annee,
       COUNT(*) AS nombre_arrivages
FROM dbo.ARRIVAGE
WHERE Arrivage_DateCreation IS NOT NULL
GROUP BY YEAR(Arrivage_DateCreation)
ORDER BY annee;

SELECT COUNT(*) AS nombre_arrivages_2025
FROM dbo.ARRIVAGE
WHERE Arrivage_DateCreation >= '2025-01-01'
  AND Arrivage_DateCreation < '2026-01-01';
