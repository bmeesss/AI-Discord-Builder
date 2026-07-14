"""
security/permissions.py
Losstaande permissie-checks. Gescheiden van business-logic zodat je dit later
makkelijk kan verfijnen (bv. een specifieke "Builder" rol toestaan i.p.v. alleen
Administrator).
"""

import discord

import config


def can_use_builder(member: discord.Member) -> bool:
    """
    Bepaalt of een lid het recht heeft om /ask te gebruiken voor server-wijzigingen.
    Standaard: alleen Administrators.
    """
    if not config.REQUIRE_ADMIN:
        return True

    if member.guild_permissions.administrator:
        return True

    return False


def missing_permission_message() -> str:
    return (
        "❌ Je hebt geen toestemming om de server-builder te gebruiken. "
        "Alleen leden met **Administrator** rechten kunnen dit."
    )


def bot_has_required_permissions(guild: discord.Guild) -> tuple[bool, list[str]]:
    """
    Controleert of de bot zelf genoeg rechten heeft in de guild om acties uit
    te voeren. Geeft (ok, ontbrekende_permissies) terug.
    """
    me = guild.me
    if me is None:
        return False, ["bot niet gevonden in guild"]

    perms = me.guild_permissions
    required = {
        "manage_channels": perms.manage_channels,
        "manage_roles": perms.manage_roles,
    }

    missing = [name for name, has_it in required.items() if not has_it]
    return (len(missing) == 0), missing
