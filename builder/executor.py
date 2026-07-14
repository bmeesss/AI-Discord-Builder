"""
builder/executor.py
Voert een gevalideerd actieplan (lijst van dicts) uit tegen een Discord guild.
Elke actie wordt los in try/except uitgevoerd zodat 1 mislukte actie niet het
hele plan blokkeert. Geeft een resultaten-overzicht terug voor logging/feedback.
"""

import logging

import discord

from builder import categories, channels, roles

logger = logging.getLogger("ai_discord_builder.executor")


class ActionResult:
    def __init__(self, action: dict, success: bool, detail: str):
        self.action = action
        self.success = success
        self.detail = detail

    def __str__(self):
        icon = "✅" if self.success else "❌"
        return f"{icon} {self.detail}"


async def execute_plan(guild: discord.Guild, actions: list[dict]) -> list[ActionResult]:
    """
    Voert elke actie in volgorde uit. Categorieën/kanalen/rollen die al bestaan
    worden overgeslagen i.p.v. dubbel aangemaakt (idempotent gedrag).
    """
    results: list[ActionResult] = []

    for action in actions:
        action_type = action.get("type")
        try:
            result = await _execute_single_action(guild, action)
            results.append(result)
        except discord.Forbidden:
            results.append(
                ActionResult(action, False, f"Geen rechten om deze actie uit te voeren: {action_type}")
            )
            logger.warning("Forbidden bij actie: %s", action)
        except discord.HTTPException as e:
            results.append(ActionResult(action, False, f"Discord API fout bij {action_type}: {e}"))
            logger.warning("HTTPException bij actie %s: %s", action, e)
        except Exception as e:
            results.append(ActionResult(action, False, f"Onverwachte fout bij {action_type}: {e}"))
            logger.exception("Onverwachte fout bij actie: %s", action)

    return results


async def _execute_single_action(guild: discord.Guild, action: dict) -> ActionResult:
    action_type = action["type"]

    if action_type == "create_category":
        cat = await categories.create_category(guild, action["name"])
        return ActionResult(action, True, f"Categorie **{cat.name}** aangemaakt (of bestond al)")

    if action_type == "create_channel":
        ch = await channels.create_channel(
            guild,
            name=action["name"],
            category_name=action.get("category"),
            channel_type=action.get("channel_type", "text"),
        )
        return ActionResult(action, True, f"Kanaal **#{ch.name}** aangemaakt (of bestond al)")

    if action_type == "delete_channel":
        ok = await channels.delete_channel(guild, action["name"])
        if ok:
            return ActionResult(action, True, f"Kanaal **{action['name']}** verwijderd")
        return ActionResult(action, False, f"Kanaal **{action['name']}** niet gevonden")

    if action_type == "move_channel":
        ok = await channels.move_channel(guild, action["name"], action["target_category"])
        if ok:
            return ActionResult(
                action, True, f"Kanaal **{action['name']}** verplaatst naar **{action['target_category']}**"
            )
        return ActionResult(action, False, f"Kanaal of categorie niet gevonden voor move_channel")

    if action_type == "create_role":
        role = await roles.create_role(
            guild,
            name=action["name"],
            permission_names=action.get("permissions", []),
            color_hex=action.get("color"),
            mentionable=action.get("mentionable", True),
            hoist=action.get("hoist", True),
        )
        return ActionResult(action, True, f"Rol **{role.name}** aangemaakt (of bestond al)")

    if action_type == "delete_role":
        ok = await roles.delete_role(guild, action["name"])
        if ok:
            return ActionResult(action, True, f"Rol **{action['name']}** verwijderd")
        return ActionResult(action, False, f"Rol **{action['name']}** niet gevonden")

    if action_type == "rename_role":
        ok = await roles.rename_role(guild, action["old_name"], action["new_name"])
        if ok:
            return ActionResult(
                action, True, f"Rol **{action['old_name']}** hernoemd naar **{action['new_name']}**"
            )
        return ActionResult(action, False, f"Rol **{action['old_name']}** niet gevonden")

    return ActionResult(action, False, f"Onbekend actietype: {action_type}")
