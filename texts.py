"""All bot texts and button layouts - no pyrogram needed (test_bot.py uses this too).

Button row format: (label, "url" | "cb", value)
"""
from __future__ import annotations

import html

BOT_NAME = "˹𝑨𝒏𝒏𝒊𝒆˼ 𝑴𝒖𝒔𝒊𝒄"
UPDATES_URL = "https://t.me/amzerox"
JINWOO_URL = "https://t.me/Notsharif_baccha"


def quote(text):
    """Wraps the whole message in a blockquote. Leaves it alone if already quoted."""
    if not text or "<blockquote" in text:
        return text
    return f"<blockquote>{text}</blockquote>"


def start_text(name: str) -> str:
    return (
        f"<b>Welcome, {html.escape(name)}!</b>\n\n"
        f"<b>{BOT_NAME}</b> lets you stream high-quality music and video "
        "directly in Telegram voice and video chats.\n\n"
        "<b>Supported platforms:</b> YouTube, Spotify, Apple Music, SoundCloud, "
        "Deezer, and more.\n\n"
        "Use the buttons below to add the bot to your group or explore the "
        "available commands."
    )


def start_rows(bot_username: str) -> list[list[tuple[str, str, str]]]:
    add_url = (
        f"https://t.me/{bot_username}?startgroup=true"
        "&admin=manage_video_chats+delete_messages+invite_users+pin_messages"
    )
    return [
        [("➕ Add me to your group", "url", add_url)],
        [("Help", "cb", "help_open")],
        [("Updates", "url", UPDATES_URL), ("Jin-Woo", "url", JINWOO_URL)],
    ]


def help_menu_text(name: str) -> str:
    return (
        f"<b>Welcome, {html.escape(name)}!</b>\n\n"
        f"<b>{BOT_NAME}</b> is a fast, reliable, and feature-rich music bot "
        "for Telegram voice and video chats.\n\n"
        "<b>Supported platforms:</b> YouTube, Spotify, Apple Music, SoundCloud, "
        "Deezer, and more.\n\n"
        "Select a category below to browse the available commands."
    )


def help_menu_rows() -> list[list[tuple[str, str, str]]]:
    return [
        [("Users", "cb", "hc_users"), ("Admins", "cb", "hc_admins"), ("Owner", "cb", "hc_owner")],
        [("Playlist", "cb", "hc_playlist"), ("Devs", "cb", "hc_devs"), ("Autoplay", "cb", "hc_autoplay")],
        [("Home", "cb", "help_back"), ("Close", "cb", "help_close")],
    ]


# key: (title, intro, section, [(command, description), ...], footer)
CATEGORIES = {
    "users": (
        "User Commands",
        "Commands available to everyone.",
        "Playback",
        [
            ("/play <name | link>", "Play a song by name or link (also works as a reply to audio)."),
            ("/queue", "Show the current queue."),
            ("/np", "Show the current song with control buttons."),
            ("/volume", "Show the current volume."),
            ("/help", "Open this help menu."),
        ],
    ),
    "admins": (
        "Admin Commands",
        "Commands available to group administrators.",
        "Playback Control",
        [
            ("/pause", "Pause the current song."),
            ("/resume", "Resume the paused song."),
            ("/skip", "Skip to the next song."),
            ("/end", "Stop playback and clear the queue."),
            ("/loop", "Repeat the current song on or off."),
            ("/shuffle", "Shuffle the songs in the queue."),
            ("/remove <number>", "Remove a song from the queue."),
            ("/volume <1-200>", "Change the volume."),
            ("/auth <reply | @user | id>", "Let a user use the admin commands without being an admin."),
            ("/unauth <reply | @user | id>", "Remove a user's authorization."),
            ("/authusers", "Show the authorized users of this chat."),
        ],
    ),
    "owner": (
        "Chat Owner Commands",
        "Configuration options available to the chat owner.",
        "Chat Settings",
        [
            (
                "/settings",
                "Manage chat settings, including play mode, administrator mode, "
                "command auto-delete, and language preferences.",
            ),
        ],
    ),
    "playlist": (
        "Playlist Commands",
        "Create, organize, and manage your personal playlists.",
        "Playlist Management",
        [
            ("/createplaylist <name>", "Create a new playlist."),
            ("/deleteplaylist <name>", "Delete one of your playlists."),
            ("/addtoplaylist <name> <song | link>", "Add a track to a playlist."),
            ("/removefromplaylist <name> <number>", "Remove a track from a playlist."),
            ("/playlistinfo <name>", "Display information about a playlist."),
            ("/myplaylists", "List all of your playlists."),
            ("/playplaylist <name>", "Play one of your playlists in the voice chat."),
        ],
    ),
    "devs": (
        "Developer Commands",
        "Commands intended for bot developers and maintainers.",
        "System",
        [
            ("/stats", "Display bot, hosting, and database statistics."),
            ("/av", "List all active voice and video chats."),
            ("/clean", "Delete old downloaded files that are not in use (keeps the current queue safe)."),
            ("/broadcast <text>", "Send a message to all groups and users (reply to a message to copy it)."),
            ("/fbroadcast", "Reply to a message to forward it to all groups and users."),
            ("/off", "Turn the bot off (asks for confirmation first)."),
            ("/clearass", "Disconnect and clear all active assistant clients."),
            ("/leaveall", "Disconnect assistants from every active chat."),
            ("/logger", "View the current logging configuration."),
        ],
    ),
    "autoplay": (
        "Autoplay Commands",
        "Keep the music going automatically.",
        "Autoplay",
        [("Coming soon", "This feature is not available yet.")],
    ),
}


def category_text(key: str) -> str:
    title, intro, section, rows = CATEGORIES[key]
    lines = "\n\n".join(f"<code>{html.escape(cmd)}</code>\n{html.escape(desc)}" for cmd, desc in rows)
    return (
        f"<blockquote><b>{BOT_NAME}</b>\n"
        f"<i>{html.escape(title)}</i>\n"
        f"{html.escape(intro)}\n\n"
        f"<b>{html.escape(section)}</b>\n\n{lines}\n\n"
        "<i>Use the buttons below to go back.</i></blockquote>"
    )


def category_rows() -> list[list[tuple[str, str, str]]]:
    return [
        [("Help", "cb", "help_open"), ("Home", "cb", "help_back")],
        [("Close", "cb", "help_close")],
    ]
