# Dictionnaire Sonasid — référence POC chatbot

**Source officielle :** [Dictionnaire_ARRIVAGE.pdf](./Dictionnaire_ARRIVAGE.pdf) — SONASID, juin 2026 (15 pages).  
Utilisé pour les requêtes T-SQL (`AZURE_SQL_PROFILE=sonasid`) et l’agent.

## Modèle relationnel

```
ARRIVAGE (1) ──< COMMANDE (1) ──< TRANSFERT >── FLOTTE
                    └── QUALITE
ARRIVAGE (1) ──< NOMINATION_NAVIRE >── NAVIRE
                    ├── COMPAGNIE_MARITIME
                    └── TRANSITAIRE
ARRIVAGE (1) ──< SUIVI_DECHARGEMENT >── SHIFT
```

Tables de référence citées : FOURNISSEUR, BANQUE, PORT, DEVISE, UTILISATEUR, STATUT, MOTIF_REJET, PRESTATAIRE, CONDUCTEUR, NATURE_MARCHANDISE, AGENT_STOCK, MARCHANDISE_REMARQUE.

---

## dbo.ARRIVAGE

Table centrale : cycle complet arrivage maritime (contractualisation → financement → logistique → douane → déchargement → tonnage → surestaries).

### 1. Identification & description

| Champ | Type | Description |
|-------|------|-------------|
| `Arrivage_Id` | INT (PK) | Identifiant unique |
| `Arrivage_Description` | VARCHAR | Libellé |
| `Arrivage_Reference` | VARCHAR | Référence interne |
| `Arrivage_ArrivageTypeId` | INT (FK) | Type d’arrivage |
| `Arrivage_Actif` | BIT | 1 = actif, 0 = archivé |
| `Arrivage_StatutInsertion` | INT/VARCHAR | Statut cycle de vie |
| `Arrivage_DateCreation` | DATETIME | Date création fiche |
| `Arrivage_UserId` | INT (FK) | Utilisateur |

### 2. Contractuel & fournisseur

| Champ | Type |
|-------|------|
| `Arrivage_FournisseurId` | INT (FK) |
| `Arrivage_NumeroFactureProforma` | VARCHAR |
| `Arrivage_DateReceptionFactureProforma` | DATE |
| `Arrivage_DateSignatureContrat` | DATE |
| `Arrivage_ConditionsAchat` | TEXT |
| `Arrivage_InformationsContractuelles` | TEXT |
| `Arrivage_Incoterm` | VARCHAR |
| `Arrivage_PrixUnitaireTotale` | DECIMAL |
| `Arrivage_DelaiPaiement` | INT |
| `Arrivage_DelaiPaiementInitial` | INT |
| `Arrivage_ModalitePaiement` | VARCHAR |

### 3. Financier & devises

`Arrivage_DeviseId`, `Arrivage_TauxChangement`, `Arrivage_TauxChangeDum`, `Arrivage_TauxChangeBooking`, `Arrivage_CoutFretEnDevise`, `Arrivage_CoutFinancement`, `Arrivage_MontantTaxes`

### 4. Lettre de crédit & banque

`Arrivage_BanqueId`, `Arrivage_NumLC`, `Arrivage_DateDepotLettreCredit`, `Arrivage_DateReceptionSwift`

### 5. Licence & douane

`Arrivage_DateDemandeLicenceImport`, `Arrivage_DateObtentionLicenceImport`, `Arrivage_NumeroLicenceImport`, `Arrivage_DateDUM`, `Arrivage_NumDUM`

### 6. Maritime — chargement

`Arrivage_PortChargementId`, `Arrivage_DateBooking`, dates prévisionnelles/réelles chargement & départ, `Arrivage_NumeroConnaissement`, `Arrivage_DateConnaissement`

### 7. Maritime — arrivée & déchargement

`Arrivage_DateReelleArrivee`, `Arrivage_DateNOR`, `Arrivage_HeureNOR`, `Arrivage_DateAccostage`, dates réelles début/fin déchargement, `Arrivage_FinDechargementFlag`, `Arrivage_TauxDechargement`, `Arrivage_DateDebutSurestaries`

### 8. Tonnage & qualité

| Champ | Usage KPI |
|-------|-----------|
| `Arrivage_TonnageTotal` | Tonnage importé (`SUM` dans POC) |
| `Arrivage_ToleranceTonnage` | Tolérance contractuelle |
| `Arrivage_PoidsDepart` / `Arrivage_PoidsArrivee` / `Arrivage_PoidsMoyen` / `Arrivage_PoidsDRAFT` | Poids |
| `Arrivage_QualiteDepartId` / `Arrivage_QualiteArriveeId` / `Arrivage_QualiteMoyenneId` | FK → QUALITE |
| `Arrivage_TermPoidsId` / `Arrivage_TermQualiteId` | Termes contractuels |

### 9. Surestaries, dispatch & draft

`Arrivage_Demurrage`, `Arrivage_SurestarieCalcule`, `Arrivage_Dispatch`, `Arrivage_MontantDispatch`, `Arrivage_HalfDispatchCalcule`, `Arrivage_Draft`, `Arrivage_DateDraft`

### 10. Assurance

`Arrivage_NumeroAssurance`

**Filtres dates POC** (`sonasid_sql.py`) : `Arrivage_DateCreation`, `Arrivage_DateReelleArrivee`, `Arrivage_DateAccostage`, `Arrivage_DateBooking`.

---

## dbo.COMMANDE

Bon de commande lié à un arrivage ; synchro SAP possible.

### Champs principaux

| Champ | Type | Description |
|-------|------|-------------|
| `Commande_Id` | INT (PK) | |
| `Commande_ArrivageId` | INT (FK) | → ARRIVAGE |
| `Commande_Type` | VARCHAR | spot, cadre, AO… |
| `Commande_Flag` | INT/BIT | État particulier |
| `Commande_Active` | BIT | 1 = active |
| `Commande_DateCreation` | DATETIME | |
| `Commande_UserId` | INT (FK) | |
| `Commande_NumeroBonCommandeSAP` | VARCHAR | SAP |
| `Commande_FournisseurId` | INT (FK) | |
| `Commande_NatureMarchandiseId` | INT (FK) | |
| `Commande_QualiteId` | INT (FK) | → QUALITE (KPI qualité) |
| `Commande_Tonnage` | DECIMAL | Tonnes commandées |
| `Commande_DeviseId` | INT (FK) | |
| `Commande_TauxChange` | DECIMAL | |
| `Commande_PrixUnitaireFinal` | DECIMAL | Prix / tonne |
| `Commande_DelaiPaiement` | INT | |
| `Commande_Incoterms` | VARCHAR | |
| `Commande_TauxDechargement` | DECIMAL | T/jour contractuel |
| `Commande_AutorisationTransfert` | BIT/VARCHAR | |

### Relations FK

`Commande_ArrivageId` → ARRIVAGE ; `Commande_FournisseurId` → FOURNISSEUR ; `Commande_QualiteId` → QUALITE ; etc.

---

## dbo.NOMINATION_NAVIRE

Nomination officielle d’un navire pour un arrivage.

### 1. Identification

`NominationNavire_Id` (PK), `NominationNavire_ArrivageId`, `NominationNavire_NavireId`, `NominationNavire_DateCreation`, `NominationNavire_UserId`

### 2. Planification voyage

`NominationNavire_DateDebutChargement`, `DateFinChargement`, `DateDepart`, `DateArrivee`, `DateLimitDelaiConfirmation`

### 3. Statut

`NominationNavire_StatutId`, `DateStatut`, `MotifRejetId`, `MotifeRetard`, `Commentaire`

### 4. Déchargement & surestaries

`NominationNavire_TauxDechargement`, `EligibiliteHalfDispatch`, `DemurrageRate`, `DemurrageDeviseId`, `Draft`

### 5. Intervenants

`NominationNavire_CompagnieMaritimeId`, `NominationNavire_TransitaireId`

**POC** : jointure avec `NAVIRE` pour « tonnage transféré par qualité par navire ».

---

## dbo.SUIVI_DECHARGEMENT

Suivi opérationnel déchargement **shift par shift** ; source surestaries et taux effectif.

| Champ | Type | Description |
|-------|------|-------------|
| `SuiviDechargement_Id` | INT (PK) | |
| `SuiviDechargement_ArrivageId` | INT (FK) | → ARRIVAGE |
| `SuiviDechargement_ShiftId` | INT (FK) | → SHIFT |
| `SuiviDechargement_QuantiteDecharge` | DECIMAL | Tonnes déchargées (shift) |
| `SuiviDechargement_QuantiteRestante` | DECIMAL | Reste à décharger |
| `SuiviDechargement_DraftFinal` | DECIMAL | Draft fin de shift |
| `SuiviDechargement_SuiviDateDechargement` | DATE | Date de suivi |
| `SuiviDechargement_DateDebutDechargement` | DATE | Début shift |
| `SuiviDechargement_HeureDebutDechargement` | TIME | |
| `SuiviDechargement_HeureFinDechargement` | TIME | Fin shift |

### Flux shift (PDF)

1. Début shift → dates/heures début  
2. Déchargement en cours → pesées  
3. Fin shift → `HeureFinDechargement` + `DraftFinal`  
4. Calcul → `QuantiteDecharge` (draft) ; `QuantiteRestante` = total − cumulé  
5. Clôture → si `QuantiteRestante = 0` → `Arrivage_FinDechargementFlag = 1` sur ARRIVAGE

---

## dbo.TRANSFERT

Transfert port/stock → site ; double pesée.

| Champ | Type | Description |
|-------|------|-------------|
| `Transfert_Id` | INT (PK) | |
| `Transfert_CommandeId` | INT (FK) | → COMMANDE |
| `Transfert_NumeroDUM` | VARCHAR | N° DUM |
| `Transfert_Recepisse` | VARCHAR | Récépissé |
| `Transfert_Actif` | BIT | 1 = actif |
| `Transfert_PremierePoids` / `Transfert_DeuxiemePoids` | DECIMAL | Pesées |
| `Transfert_PoidsNet` | DECIMAL | **PremierePoids − DeuxiemePoids** |
| `Transfert_DatePremierePoids` / `Transfert_DateDeuxiemePoids` | DATETIME | Dates pesées |
| `Transfert_PremierePoidsUserId` / `Transfert_DeuxiemePoidsUserId` | INT (FK) | Opérateurs pesée |
| `Transfert_ReceptionSite` | VARCHAR | Site de réception |
| `Transfert_MarchandiseRemarqueId` / `Transfert_MarchandiseRemarques` | INT / TEXT | Remarques marchandise |
| `Transfert_PrestataireChargementId` / `Transfert_PrestataireTransfertId` | INT (FK) | → PRESTATAIRE |
| `Transfert_ConducteurId` | INT (FK) | → CONDUCTEUR |
| `Transfert_FlotteId` | INT (FK) | → FLOTTE (véhicule) |
| `Transfert_StockAgentId` | INT (FK) | → AGENT_STOCK |
| `Transfert_Commentaire` | TEXT | |
| `Transfert_DateCreation` | DATETIME | |
| `Transfert_UserId` | INT (FK) | |

**POC** : `SUM(Transfert_PoidsNet)` + `COMMANDE` + `QUALITE` ; lien camion via `Transfert_FlotteId` → `FLOTTE`.

---

## dbo.NAVIRE

Référentiel des navires (identité, caractéristiques techniques, statut).

| Champ | Type | Description |
|-------|------|-------------|
| `Navire_Id` | INT (PK) | Identifiant unique |
| `Navire_Nom` | VARCHAR | Nom du navire |
| `Navire_IMO` | VARCHAR | Numéro IMO |
| `Navire_CompagnieId` | INT (FK) | Compagnie maritime |
| `Navire_ImmatriculationPaysId` | INT (FK) | Pays d’immatriculation |
| `Navire_ImmatriculationPortId` | INT (FK) | Port d’immatriculation |
| `Navire_AnneeConstruction` | INT | Année de construction |
| `Navire_LongueurMetres` | DECIMAL | Longueur (m) |
| `Navire_LargeurMetres` | DECIMAL | Largeur (m) |
| `Navire_TonnageBrut` | DECIMAL | Tonnage brut |
| `Navire_TonnageNet` | DECIMAL | Tonnage net |
| `Navire_DeadweightTonnage` | DECIMAL | Port en lourd (DWT) |
| `Navire_Observations` | TEXT | Observations |
| `Navire_DateValidationStatut` | DATETIME | Validation statut |
| `Navire_Active` | BIT | 1 = actif (KPI « navires actifs ») |
| `Navire_DateCreation` | DATETIME | Date création fiche |

### Relations FK

`NOMINATION_NAVIRE.NominationNavire_NavireId` → NAVIRE ; un navire peut être nominé sur plusieurs arrivages.

**POC** : jointure `ARRIVAGE → NOMINATION_NAVIRE → NAVIRE` pour navires en déchargement, tonnage par navire, classements.

---

## dbo.QUALITE

Référentiel des qualités / grades de marchandise.

| Champ | Type | Description |
|-------|------|-------------|
| `Qualite_Id` | INT (PK) | Identifiant unique |
| `Qualite_Libelle` | VARCHAR | Libellé affiché (KPI) |
| `Qualite_Active` | BIT | 1 = active (filtre par défaut POC) |
| `Qualite_Affectation` | VARCHAR | Affectation métier |

### Relations FK

`COMMANDE.Commande_QualiteId` → QUALITE ; `ARRIVAGE` peut aussi référencer QUALITE via `Arrivage_QualiteDepartId`, `Arrivage_QualiteArriveeId`, `Arrivage_QualiteMoyenneId`.

**POC** : `GROUP BY Qualite_Libelle` pour tonnage commandé / transféré par qualité.

---

## dbo.FLOTTE

Parc de véhicules (camions) pour les transferts port → site.

| Champ | Type | Description |
|-------|------|-------------|
| `Flotte_Id` | INT (PK) | Identifiant unique |
| `Flotte_TransporteurId` | INT (FK) | Transporteur |
| `Flotte_TypeFlotteId` | INT (FK) | Type de véhicule |
| `Flotte_Immatriculation` | VARCHAR | Immatriculation |
| `Flotte_DateMiseEnService` | DATE | Mise en service |
| `Flotte_CapaciteTonnes` | DECIMAL | Capacité (t) |
| `Flotte_GPSID` | VARCHAR | Identifiant GPS |
| `Flotte_ConducteurNom` | VARCHAR | Nom conducteur |
| `Flotte_ConducteurPrenom` | VARCHAR | Prénom conducteur |
| `Flotte_ConducteurCIN` | VARCHAR | CIN conducteur |
| `Flotte_Blacklisted` | BIT | Liste noire |
| `Flotte_Actif` | BIT | 1 = actif |
| `Flotte_DateCreation` | DATETIME | |
| `Flotte_UserId` | INT (FK) | |
| `Flotte_Flux` | VARCHAR | Flux / sens |

### Relations FK

`TRANSFERT.Transfert_FlotteId` → FLOTTE ; `TRANSFERT.Transfert_ConducteurId` → CONDUCTEUR (référentiel séparé).

**POC** : extension possible — « quel camion pour ce transfert » via `TRANSFERT JOIN FLOTTE`.

---

## KPI officiels (client)

Fichier SQL : [formules_kpi_officielles.sql](./formules_kpi_officielles.sql)

| KPI | Paramètre |
|-----|-----------|
| Nombre des arrivages | — |
| Nombre des arrivages par fournisseur | `@Fournisseur` |
| Tonnage importé par fournisseur | `@Fournisseur` |
| Tonnage par qualité par fournisseur | `@Fournisseur` |
| Tonnage transféré par qualité | — (ligne par `Transfert_PoidsNet`) |
| Tonnage transféré par qualité par navire | `@Navire_Id` |

**Correction POC** : le `GROUP BY` client sur « tonnage par qualité par fournisseur » inclut `Commande_Tonnage` ; l’agrégation correcte est `GROUP BY Commande_QualiteId, Qualite_Libelle` uniquement.

## KPI implémentés (`backend/llm/sonasid_sql.py`)

| Question (exemple) | Implémentation |
|--------------------|----------------|
| Nombre des arrivages | `COUNT(*)` ARRIVAGE |
| Arrivages / tonnage par fournisseur | `Arrivage_FournisseurId` |
| Tonnage importé | `SUM(Arrivage_TonnageTotal)` |
| Tonnage par qualité par fournisseur | COMMANDE + QUALITE + ARRIVAGE |
| Tonnage transféré par qualité | TRANSFERT + COMMANDE + QUALITE (détail) |
| Tonnage transféré par qualité par navire | + NOMINATION_NAVIRE + NAVIRE, `SUM` |
| Navires actifs | NAVIRE |
| Navires en déchargement | `FinDechargementFlag=0`, `DateDebutReelleDechargement` renseignée |
| Liste navires en déchargement | idem + `QuantiteRestante` (dernier shift) |
| Tonnage déchargé | `SUM(SuiviDechargement_QuantiteDecharge)` sur arrivages en cours (ou période) |
| Tonnage restant | `SUM` du dernier `QuantiteRestante` par arrivage en cours |
| Taux de déchargement | `AVG(Arrivage_TauxDechargement)` ou liste par navire |
| Tonnage déchargé par mois | série sur `DateDebutReelleDechargement` |
| Liste des qualités | `QUALITE` (actives par défaut) |
| Tonnage commandé par qualité | `SUM(Commande_Tonnage)` + `COMMANDE` + `QUALITE` + filtre `ARRIVAGE` |
| Tonnage transféré par qualité (répartition) | `SUM(Transfert_PoidsNet)` par qualité (défaut chat) |
| Tonnage transféré par qualité (détail) | une ligne par transfert (formule officielle, max 500) |

### Qualité & commandes (rappel)

- **Qualité commande** : `COMMANDE.Commande_QualiteId` → `QUALITE.Qualite_Libelle`
- **Tonnage commandé** : `COMMANDE.Commande_Tonnage`
- **Tonnage transféré** : `TRANSFERT.Transfert_PoidsNet` (qualité via la commande)

### Règle « en déchargement » (POC)

Un navire est **en déchargement** si l’arrivage lié vérifie :

- `Arrivage_DateDebutReelleDechargement IS NOT NULL`
- `Arrivage_FinDechargementFlag = 0` (ou NULL)

---

## Variables `.env` (tables)

```env
AZURE_SQL_TABLE_ARRIVAGE=dbo.ARRIVAGE
AZURE_SQL_TABLE_COMMANDE=dbo.COMMANDE
AZURE_SQL_TABLE_TRANSFERT=dbo.TRANSFERT
AZURE_SQL_TABLE_NAVIRE=dbo.NAVIRE
AZURE_SQL_TABLE_QUALITE=dbo.QUALITE
AZURE_SQL_TABLE_NOMINATION_NAVIRE=dbo.NOMINATION_NAVIRE
# AZURE_SQL_TABLE_SUIVI_DECHARGEMENT=dbo.SUIVI_DECHARGEMENT
```

---

## Extensions à coder (formules client requises)

- Tonnage déchargé / restant (`SUIVI_DECHARGEMENT`)
- Surestaries (`Arrivage_Demurrage`, `NominationNavire_DemurrageRate`)
- Filtres `Arrivage_Actif = 1`, `Transfert_Actif = 1`
- Nominations par statut / transitaire / compagnie maritime
