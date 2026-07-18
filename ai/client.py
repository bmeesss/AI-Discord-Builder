"""
ai/client.py

Verantwoordelijk voor het aanroepen van de AI provider (Groq of OpenAI) en het
veilig parsen/valideren van de JSON response volgens ons action-schema.

Belangrijk: dit bestand vertrouwt de AI-output NOOIT blind.
Alles wordt gevalideerd voordat het bij de executor terechtkomt.
"""

import json
import logging

import config
from ai.prompts import SYSTEM_PROMPT, build_user_prompt
from ai.validation import PlanValidationError, parse_plan


logger = logging.getLogger(
    "ai_discord_builder.ai_client"
)


class AIPlanError(Exception):
    """
    Raised wanneer de AI geen bruikbaar of veilig plan teruggeeft.
    """
    pass





class AIClient:


    def __init__(self):

        self.provider = config.AI_PROVIDER


        if self.provider == "groq":

            from groq import AsyncGroq

            self._client = AsyncGroq(
                api_key=config.GROQ_API_KEY
            )

            self._model = config.GROQ_MODEL



        elif self.provider == "openai":

            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=config.OPENAI_API_KEY
            )

            self._model = config.OPENAI_MODEL



        else:

            raise ValueError(
                f"Onbekende AI_PROVIDER: {self.provider}"
            )





    async def generate_plan(
        self,
        user_instruction: str,
        server_context: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict:
        """
        Stuurt instructie naar AI en geeft gevalideerd plan terug.
        """


        user_prompt = build_user_prompt(
            user_instruction,
            server_context,
            validation_errors=validation_errors,
        )


        try:

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    },
                ],
                temperature=0.3,
                response_format={
                    "type": "json_object"
                },
            )


            raw_content = (
                response
                .choices[0]
                .message
                .content
            )


        except Exception as e:

            logger.exception(
                "AI API call mislukt"
            )

            raise AIPlanError(
                f"AI provider fout: {e}"
            ) from e



        plan = self._parse_and_validate(
            raw_content
        )

        return plan.to_legacy_dict()







    def _parse_and_validate(
        self,
        raw_content: str
    ):


        cleaned = raw_content.strip()



        # Defensive JSON cleanup

        if cleaned.startswith("```"):

            cleaned = cleaned.strip("`")


            if cleaned.lower().startswith(
                "json"
            ):

                cleaned = cleaned[4:]


            cleaned = cleaned.strip()





        try:

            data = json.loads(
                cleaned
            )


        except json.JSONDecodeError as e:

            logger.error(
                "AI gaf geen valide JSON: %s",
                raw_content[:500]
            )

            raise AIPlanError(
                "De AI gaf geen valide JSON terug."
            ) from e





        try:
            return parse_plan(data)
        except PlanValidationError as e:
            raise AIPlanError(str(e)) from e
