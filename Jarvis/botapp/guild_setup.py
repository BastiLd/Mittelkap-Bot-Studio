"""Initialize unseen servers without copying another server's destination IDs."""


def initialize_guild(service, guild):
    store, base = service.store, service.config.base
    if store.state(guild.id, "guild_initialized_v1"):
        return
    existing = store.settings(guild.id)
    configured_here = any(value and guild.get_channel_or_thread(int(value)) is not None
                          for value in base.get("channels", {}).values())
    explicit = str(guild.id) in base.get("guilds", {})
    history = store.db.execute("SELECT 1 FROM activity WHERE guild=? LIMIT 1", (guild.id,)).fetchone()
    if not existing and not configured_here and not explicit and not history:
        clean = {
            "_isolated_server": True,
            "channels": {k: None for k in base.get("channels", {})},
            "links": {k: "" for k in base.get("links", {})}, "sources": [],
            "admin_role_ids": [], "moderator_role_ids": [], "protected_role_ids": [],
            "level_roles": {}, "creator_name": guild.name,
            "command_settings": {k: {**v, "allowed_channel_ids": []} for k, v in base.get("command_settings", {}).items()},
            "embed_templates": {},
            "messages": {"welcome": "Willkommen {name} auf {server}! Mit /hilfe findest du die Möglichkeiten.",
                         "farewell": "{name} hat den Server verlassen. Alles Gute!",
                         "birthday": "Alles Gute zum Geburtstag, {name}!"},
        }
        # Templates are replacement maps, not recursive overlays of another server.
        store.save_settings(guild.id, clean)
    store.set_state(guild.id, "guild_initialized_v1", "1")
