-- Formules KPI officielles Sonasid (client)
-- Implémentées dans backend/llm/sonasid_sql.py (@Fournisseur / @Navire → id ou nom dans la question)

-- Nombre des arrivages
SELECT COUNT(*) AS nombre_arrivages FROM dbo.ARRIVAGE;

-- Nombre des arrivages par fournisseur
SELECT COUNT(*) AS nombre_arrivages
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = @Fournisseur;

-- Tonnage importé par fournisseur
SELECT SUM(Arrivage_TonnageTotal) AS tonnage_importe
FROM dbo.ARRIVAGE
WHERE Arrivage_FournisseurId = @Fournisseur;

-- Tonnage par qualité par fournisseur
-- Note POC : le GROUP BY client inclut Commande_Tonnage (incorrect pour un SUM) ;
-- le code utilise uniquement Commande_QualiteId + Qualite_Libelle.
SELECT c.Commande_QualiteId,
       q.Qualite_Libelle,
       SUM(c.Commande_Tonnage) AS tonnage
FROM dbo.COMMANDE c
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id
INNER JOIN dbo.ARRIVAGE a ON c.Commande_ArrivageId = a.Arrivage_Id
WHERE a.Arrivage_FournisseurId = @Fournisseur
GROUP BY c.Commande_QualiteId, q.Qualite_Libelle;

-- Tonnage transféré par qualité (par commande — une ligne par transfert)
SELECT q.Qualite_Libelle,
       c.Commande_QualiteId,
       t.Transfert_PoidsNet
FROM dbo.TRANSFERT t
INNER JOIN dbo.COMMANDE c ON t.Transfert_CommandeId = c.Commande_Id
INNER JOIN dbo.QUALITE q ON c.Commande_QualiteId = q.Qualite_Id;

-- Navires en déchargement (extension POC — snapshot port)
SELECT COUNT(DISTINCT nv.Navire_Id) AS nombre_navires_en_dechargement
FROM dbo.ARRIVAGE a
INNER JOIN dbo.NOMINATION_NAVIRE nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId
INNER JOIN dbo.NAVIRE nv ON nn.NominationNavire_NavireId = nv.Navire_Id
WHERE (a.Arrivage_FinDechargementFlag = 0 OR a.Arrivage_FinDechargementFlag IS NULL)
  AND a.Arrivage_DateDebutReelleDechargement IS NOT NULL;

-- Tonnage transféré par qualité par navire
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
GROUP BY a.Arrivage_Id, nv.Navire_Nom, c.Commande_QualiteId, q.Qualite_Libelle;
