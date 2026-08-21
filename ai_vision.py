"""
Phase 2 — AI Image Analyzer

Rôle (section 7 du cahier des charges) :

    Envoyer l'image à un modèle de vision et récupérer une réponse
    structurée décrivant le contenu du ticket de pari, ainsi qu'une
    classification préliminaire (image_type) et un niveau de confiance.

Important : ce module NE DÉCIDE PAS encore quoi faire de cette
classification (créer un pari, le mettre à jour, l'ignorer...). C'est le
rôle de la Phase 3 (classification / routage métier) et de la Phase 4
(matching), qui liront la table `image_analysis` remplie ici.

On utilise le "tool use" de l'API Claude (function calling) plutôt qu'un
simple prompt demandant du JSON en texte libre : c'est plus fiable, le
modèle est contraint de respecter le schéma plutôt que de le "décrire"
en langage naturel, ce qui évite les erreurs de parsing.
"""

import base64
import json
import mimetypes
from pathlib import Path

import anthropic


# Schéma de sortie forcé, directement dérivé de l'exemple JSON en section 7
# du cahier des charges (image_type, confidence, match, bet, stake, ...).
BET_ANALYSIS_TOOL = {
    "name": "record_bet_analysis",
    "description": (
        "Enregistre l'analyse structurée d'une capture d'écran de pari sportif."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_type": {
                "type": "string",
                "enum": ["new_bet", "winning_bet", "unknown", "ignored"],
                "description": (
                    "new_bet = ticket d'un pari qui vient d'être placé (statut "
                    "généralement en attente). winning_bet = capture montrant "
                    "explicitement qu'un pari a été gagné (statut gagnant, gain "
                    "encaissé affiché). unknown = image de pari mais impossible "
                    "de déterminer le type avec certitude. ignored = l'image ne "
                    "contient pas de ticket de pari exploitable."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Niveau de confiance de 0 à 1 dans cette classification.",
            },
            "team_1": {"type": "string"},
            "team_2": {"type": "string"},
            "competition": {"type": "string"},
            "event_date": {
                "type": "string",
                "description": "Date du match si visible, au format AAAA-MM-JJ (ex: '2026-08-19').",
            },
            "event_time": {
                "type": "string",
                "description": "Heure du match si visible, au format 24h HH:MM (ex: '21:45').",
            },
            "market": {
                "type": "string",
                "description": "Type de marché / pari (ex: 'Over 0.5 Goals - First Half').",
            },
            "selection": {"type": "string"},
            "odds": {"type": "number"},
            "stake": {"type": "number"},
            "potential_return": {"type": "number"},
            "status_on_ticket": {
                "type": "string",
                "description": "Statut visible sur le ticket lui-même si présent (ex: PENDING, WON).",
            },
            "confirmed_payout": {
                "type": "number",
                "description": "Montant réellement gagné/encaissé, si visible (winning_bet).",
            },
            "notes": {
                "type": "string",
                "description": "Toute information utile non couverte par les autres champs.",
            },
        },
        "required": ["image_type", "confidence"],
    },
}

SYSTEM_PROMPT = """Tu analyses des captures d'écran de paris sportifs (tickets de bookmaker).

Ta tâche : extraire les informations visibles sur le ticket et classifier l'image
en appelant l'outil record_bet_analysis.

Règles importantes :
- Ne remplis un champ que si l'information est clairement visible sur l'image. Ne
  devine jamais une valeur non affichée.
- Si l'image ne montre pas de ticket de pari exploitable (capture d'écran non
  liée, photo quelconque, texte de discussion...), classe-la en "ignored".
- Si tu vois un ticket mais que tu ne peux pas déterminer avec certitude s'il
  s'agit d'un nouveau pari ou d'une confirmation de gain, classe-le "unknown"
  plutôt que de deviner.
- Le niveau de confidence doit refléter honnêtement ton incertitude, pas
  systématiquement une valeur haute.
"""


def _encode_image(image_path: Path) -> tuple[str, str]:
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type is None:
        mime_type = "image/jpeg"
    data = image_path.read_bytes()
    return base64.b64encode(data).decode("utf-8"), mime_type


def analyze_image(image_path: Path, api_key: str, model: str) -> dict:
    """
    Envoie l'image au modèle et retourne un dict Python avec les champs du
    schéma BET_ANALYSIS_TOOL. Lève une exception en cas d'échec (réseau,
    clé API invalide, réponse inattendue...) — c'est à l'appelant de
    décider comment logguer/gérer l'erreur.
    """
    b64_data, mime_type = _encode_image(image_path)

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[BET_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "record_bet_analysis"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyse ce ticket de pari et appelle record_bet_analysis.",
                    },
                ],
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_bet_analysis":
            return block.input

    raise RuntimeError(
        "Le modèle n'a pas retourné d'appel à record_bet_analysis "
        f"(réponse brute : {response.content})"
    )
