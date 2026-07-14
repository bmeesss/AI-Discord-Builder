"""
builder/roles.py
Alle Discord-acties die met rollen te maken hebben: aanmaken, verwijderen,
hernoemen, permissies instellen.
"""

import discord

# Mapping van onze schema-permissienamen naar discord.Permissions kwargs
PERMISSION_MAP = {
    "manage_messages": "manage_messages",
    "moderate_members": "moderate_members",
    "kick_members": "kick_members",
    "ban_members": "ban_members",
    "manage_channels": "manage_channels",
    "manage_roles": "manage_roles",
    "mention_everyone": "mention_everyone",
    "view_channel": "view_channel",
    "connect": "connect",
    "speak": "speak",
    "administrator": "administrator",
}


def build_permissions(permission_names: list[str]) -> discord.Permissions:
    kwargs = {}
    for name in permission_names:
        discord_attr = PERMISSION_MAP.get(name)
        if discord_attr:
            kwargs[discord_attr] = True
    return discord.Permissions(**kwargs)


async def create_role(
    guild: discord.Guild,
    name: str,
    permission_names: list[str] | None = None,
    color_hex: str | None = None,
    mentionable: bool = True,
    hoist: bool = True,
) -> discord.Role:
    existing = discord.utils.get(guild.roles, name=name)
    if existing:
        return existing

    perms = build_permissions(permission_names or [])

    color = discord.Color.default()
    if color_hex:
        try:
            color = discord.Color(int(color_hex.lstrip("#"), 16))
        except ValueError:
            pass

    return await guild.create_role(
        name=name,
        permissions=perms,
        color=color,
        mentionable=mentionable,
        hoist=hoist,
        reason="AI-Discord-Builder: rol aangemaakt",
    )


async def delete_role(guild: discord.Guild, name: str) -> bool:
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        return False
    await role.delete(reason="AI-Discord-Builder: rol verwijderd op verzoek")
    return True


async def rename_role(guild: discord.Guild, old_name: str, new_name: str) -> bool:
    role = discord.utils.get(guild.roles, name=old_name)
    if not role:
        return False
    await role.edit(name=new_name, reason="AI-Discord-Builder: rol hernoemd")
    return True
