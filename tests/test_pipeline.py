import sys
import os


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.pipeline.pipeline import process_question


TEST_CASES = [
    {
        "question": "taux de disponibilité",
        "expected_keys": ["TD_percent"],
    },
    {
        "question": "temps requis",
        "expected_keys": ["TR_percent"],
    },
    {
        "question": "MTBF",
        "expected_keys": ["MTBF_secondes"],
    },
    {
        "question": "MTTR",
        "expected_keys": ["MTTR_secondes"],
    },
    {
        "question": "rendement",
        "expected_keys": ["Rendement_percent"],
    },
    {
        "question": "consommation électrique",
        "expected_keys": [
            "Consommation_EAF",
            "Consommation_LF",
            "Consommation_Totale",
            "Consommation_MWh",
        ],
    },
    {
        "question": "consommation oxygène",
        "expected_keys": ["Consommation_Oxygène"],
    },
    {
        "question": "consommation carbone",
        "expected_keys": ["Consommation_Carbon"],
    },
    {
        "question": "nombre de coulées",
        "expected_keys": ["result"],
    },
    {
        "question": "nombre des brames",
        "expected_keys": ["result"],
    },
    {
        "question": "production",
        "expected_keys": ["result"],
    },
    {
        "question": "consommation par ferraille",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "taux de disponibilité 2024-01-01",
        "expected_keys": ["TD_percent"],
    },
    {
        "question": "temps requis 2024-01-01",
        "expected_keys": ["TR_percent"],
    },
    {
        "question": "MTBF 2024-01-01",
        "expected_keys": ["MTBF_secondes"],
    },
    {
        "question": "MTTR 2024-01-01",
        "expected_keys": ["MTTR_secondes"],
    },
    # ======== KPI performance avec filtres année/mois/période ========
    {
        "question": "taux de disponibilité en 2025",
        "expected_keys": ["TD_percent"],
    },
    {
        "question": "temps requis 2025-01",
        "expected_keys": ["TR_percent"],
    },
    {
        "question": "MTBF en 2025",
        "expected_keys": ["MTBF_secondes"],
    },
    {
        "question": "MTTR du 2025-01-01 au 2025-01-31",
        "expected_keys": ["MTTR_secondes"],
    },
    {
        "question": "rendement en 2025",
        "expected_keys": ["Rendement_percent"],
    },
    {
        "question": "poids ferrailles en 2025",
        "expected_keys": ["result"],
    },
    {
        "question": "consommation électrique grade S275 2024-01-01",
        "expected_any_keys": [
            ["Consommation_EAF", "Consommation_LF", "Consommation_Totale", "Consommation_MWh"],
            ["message"],
        ],
    },
    {
        "question": "consommation oxygène grade S355 2024-01-01",
        "expected_any_keys": [
            ["Consommation_Oxygène"],
            ["message"],
        ],
    },
    {
        "question": "consommation carbone 2024-01-01",
        "expected_any_keys": [
            ["Consommation_Carbon"],
            ["message"],
        ],
    },
    {
        "question": "consommation gpl",
        "expected_any_keys": [
            ["Consommation_GPL"],
            ["message"],
        ],
    },
    {
        "question": "production grade S275 2024-01-01",
        "expected_keys": ["result"],
    },
    {
        "question": "nombre de coulées grade S275 2024-01-01",
        "expected_keys": ["result"],
    },
    {
        "question": "nombre des brames 2024-01-01",
        "expected_keys": ["result"],
    },
    {
        "question": "poids brame",
        "expected_keys": ["result"],
    },
    {
        "question": "poids des brames 2024-01-01",
        "expected_keys": ["result"],
    },
    # ======== Tests filtres année/mois/période (données présentes en 2025) ========
    {
        "question": "nombre de brames en 2025",
        "expected_keys": ["result"],
    },
    {
        "question": "nombre de brames 2025-01",
        "expected_keys": ["result"],
    },
    {
        "question": "production en 2025",
        "expected_keys": ["result"],
    },
    {
        "question": "production par grade top 5 en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "nombre de coulées par grade top 5 en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "nombre de coulées par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "nombre de coulées par jour 2025-01",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "nombre de brames par jour 2025-01",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "production par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    # ======== Consommations (filtres + séries) ========
    {
        "question": "consommation électrique en 2025",
        "expected_any_keys": [
            ["Consommation_EAF", "Consommation_LF", "Consommation_Totale", "Consommation_MWh"],
            ["message"],
        ],
    },
    {
        "question": "consommation électrique 2025-01",
        "expected_any_keys": [
            ["Consommation_EAF", "Consommation_LF", "Consommation_Totale", "Consommation_MWh"],
            ["message"],
        ],
    },
    {
        "question": "consommation électrique par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "consommation électrique par grade top 5 en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "consommation oxygène par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "consommation gpl par grade top 5 en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    # ======== Restants Excel : largeur/épaisseur + ferrailles par catégorie ========
    {
        "question": "poids des brames par largeur epaisseur en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par largeur epaisseur par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par largeur en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par epaisseur en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par largeur par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "poids des brames par epaisseur par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "conso ferrailles en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
    {
        "question": "conso ferrailles par mois en 2025",
        "expected_keys": ["result"],
        "expect_list": True,
    },
]


def validate_response(question, response, expected_keys=None, expect_list=False, expected_any_keys=None):
    if not isinstance(response, dict):
        raise AssertionError(f"Réponse invalide pour '{question}': dict attendu")

    if response.get("question") != question:
        raise AssertionError(f"Champ question incorrect pour '{question}'")

    if expected_keys:
        for key in expected_keys:
            if key not in response:
                raise AssertionError(f"Clé manquante '{key}' pour '{question}'")

    if expected_any_keys:
        matches = False
        for key_group in expected_any_keys:
            if all(k in response for k in key_group):
                matches = True
                break
        if not matches:
            raise AssertionError(
                f"Aucun groupe de clés attendu trouvé pour '{question}': {expected_any_keys}"
            )

    if expect_list and not isinstance(response.get("result"), list):
        raise AssertionError(f"'result' doit être une liste pour '{question}'")


def run_all_tests():
    passed = 0

    print("\n=== TEST KPI PIPELINE ===")
    for case in TEST_CASES:
        question = case["question"]
        expected_keys = case.get("expected_keys")
        expected_any_keys = case.get("expected_any_keys")
        expect_list = case.get("expect_list", False)

        response = process_question(question)
        validate_response(
            question,
            response,
            expected_keys=expected_keys,
            expect_list=expect_list,
            expected_any_keys=expected_any_keys,
        )

        print(f"[OK] {question}")
        print(f"     -> {response}")
        passed += 1

    print(f"\nRésumé: {passed}/{len(TEST_CASES)} tests passés.")


if __name__ == "__main__":
    run_all_tests()
