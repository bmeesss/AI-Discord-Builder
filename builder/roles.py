"""
builder/roles.py

All Discord actions related to roles:
- create
- delete
- rename
- permissions

Includes case-insensitive role searching.
"""

import discord


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


def find_role(
    guild: discord.Guild,
    name: str
) -> discord.Role | None:

    name = name.lower().strip()

    for role in guild.roles:
        if role.name.lower().strip() == name:
            return role

    return None



def build_permissions(
    permission_names: list[str]
) -> discord.Permissions:

    kwargs = {}

    for permission in permission_names:
        discord_permission = PERMISSION_MAP.get(permission)

        if discord_permission:
            kwargs[discord_permission] = True

    return discord.Permissions(**kwargs)



async def create_role(
    guild: discord.Guild,
    name: str,
    permission_names: list[str] | None = None,
    color_hex: str | None = None,
    mentionable: bool = True,
    hoist: bool = True,
) -> discord.Role:


    existing = find_role(
        guild,
        name
    )

    if existing:
        return existing


    permissions = build_permissions(
        permission_names or []
    )


    color = discord.Color.default()

    if color_hex:
        try:
            color = discord.Color(
                int(
                    color_hex.replace("#", ""),
                    16
                )
            )

        except ValueError:
            pass


    return await guild.create_role(
        name=name,
        permissions=permissions,
        color=color,
        mentionable=mentionable,
        hoist=hoist,
        reason="AI-Discord-Builder: role created"
    )



async def delete_role(
    guild: discord.Guild,
    name: str
) -> bool:


    role = find_role(
        guild,
        name
    )


    if not role:
        return False


    await role.delete(
        reason="AI-Discord-Builder: role deleted"
    )

    return True



async def rename_role(
    guild: discord.Guild,
    old_name: str,
    new_name: str
) -> bool:


    role = find_role(
        guild,
        old_name
    )


    if not role:
        return False


    await role.edit(
        name=new_name,
        reason="AI-Discord-Builder: role renamed"
    )


    return True