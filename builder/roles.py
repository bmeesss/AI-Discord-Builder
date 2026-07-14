"""
builder/roles.py

All Discord actions related to roles:
- Create
- Delete
- Rename
- Permissions
"""

import discord


# Mapping of schema permissions to discord.Permissions
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


def simplify_name(name: str) -> str:
    """
    Removes emojis and symbols for better matching.

    Example:
    "🛡️ Moderator" -> "moderator"
    """

    name = name.lower().strip()

    return "".join(
        c for c in name
        if c.isalnum() or c in " _-"
    ).strip()


def find_role(
    guild: discord.Guild,
    name: str
) -> discord.Role | None:
    """
    Finds a role ignoring:
    - capitalization
    - emojis
    - symbols
    """

    search = simplify_name(name)

    for role in guild.roles:

        role_name = simplify_name(
            role.name
        )

        if role_name == search:
            return role

    return None


def build_permissions(
    permission_names: list[str]
) -> discord.Permissions:

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

    existing = find_role(
        guild,
        name
    )

    if existing:
        return existing

    perms = build_permissions(
        permission_names or []
    )

    color = discord.Color.default()

    if color_hex:
        try:
            color = discord.Color(
                int(color_hex.lstrip("#"), 16)
            )
        except ValueError:
            pass

    return await guild.create_role(
        name=name,
        permissions=perms,
        color=color,
        mentionable=mentionable,
        hoist=hoist,
        reason="AI-Discord-Builder: role created",
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