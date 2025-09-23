# ============================ CONFIG ============================
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# Ottieni il token del bot dall'ambiente, se non presente solleva errore
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

# Lista degli ID dei server dove il bot sarà attivo
GUILD_IDS = [1358713154116259892, 687741871757197312]

# Impostazioni di default per immagini e ruoli
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
MAX_ROLES = 5  # massimo ruoli per evento
DEFAULT_SLOTS = 4  # slot per ruolo

# ============================ BOT ============================
intents = discord.Intents.default()  # definisce quali eventi Discord riceve il bot
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================ PERSISTENZA ============================
# Carica prenotazioni da file JSON oppure inizializza dizionario vuoto
if os.path.exists("prenotazioni.json"):
    with open("prenotazioni.json", "r") as f:
        bookings = json.load(f)
else:
    bookings = {}

# Salva le prenotazioni su file
def save_bookings():
    with open("prenotazioni.json", "w") as f:
        json.dump(bookings, f, indent=4)

# ============================ FUNZIONE EMBED ============================
def generate_embed(data: str, desc: str, active_roles: dict, image_url: str = BACKGROUND_URL):
    """Crea un embed con info sui ruoli e utenti prenotati"""
    embed = discord.Embed(title="📋 Prenotazioni Piloti",
                          description=f"📅 Missione: {data}\n📝 {desc}",
                          color=0x1abc9c)
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info["plane"] != "Non Attivo" else "❌ Non Attivo"
        piloti = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}",
                        value=f"Prenotati: {piloti}", inline=False)
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")
    embed.set_image(url=image_url)
    return embed

# ============================ SELEZIONE IMMAGINE ============================
class ImageLinkModal(discord.ui.Modal, title="Inserisci link immagine personalizzata"):
    image_url = discord.ui.TextInput(label="URL immagine", placeholder="https://...", max_length=500)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.selected_image = self.image_url.value.strip() or BACKGROUND_URL
        await interaction.response.send_message("📸 Immagine personalizzata impostata!", ephemeral=True)
        await self.parent_view.continue_setup(interaction)

class ImageSelectButton(discord.ui.Button):
    def __init__(self, parent_view, label, url=None):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.url = url

    async def callback(self, interaction: discord.Interaction):
        if self.url:
            self.parent_view.selected_image = self.url
            await interaction.response.send_message("🖼️ Usata immagine di default!", ephemeral=True)
            await self.parent_view.continue_setup(interaction)
        else:
            await interaction.response.send_modal(ImageLinkModal(self.parent_view))

class ImageSelectView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.add_item(ImageSelectButton(parent_view, label="Usa immagine di default", url=BACKGROUND_URL))
        self.add_item(ImageSelectButton(parent_view, label="Inserisci link immagine personalizzata"))

# ============================ BOTTONI PRENOTAZIONE ============================
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane, image_url):
        is_active = active_roles[role]["plane"] == plane
        color = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=not is_active)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        already_in_role = next((r for r, info in self.active_roles.items() if user in info["users"]), None)

        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(f"⚠️ Sei già prenotato in **{already_in_role}**! Rimuoviti prima da quel ruolo.", ephemeral=True)
            return

        role_info = self.active_roles[self.role_name]

        if user in role_info["users"]:
            role_info["users"].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(f"❌ Hai rimosso la tua prenotazione da **{self.role_name}**.", ephemeral=True)
            return

        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(f"⚠️ {self.role_name} è già pieno!", ephemeral=True)
            return

        role_info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(f"✅ Prenotazione in **{self.role_name}** confermata!", ephemeral=True)

class ChangePlaneButton(discord.ui.Button):
    def __init__(self, data, desc, active_roles, image_url):
        super().__init__(label="Cambia Aereo", style=discord.ButtonStyle.secondary)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        view = PlaneSelectView(self.data, self.desc, self.active_roles, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)

class BookingView(discord.ui.View):
    def __init__(self, data, desc, active_roles, plane, image_url):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, data, desc, active_roles, plane, image_url))
        self.add_item(ChangePlaneButton(data, desc, active_roles, image_url))

class PlaneSelect(discord.ui.Select):
    def __init__(self, data, desc, active_roles, image_url):
        planes = list({info["plane"] for info in active_roles.values() if info["plane"] != "Non Attivo"})
        options = [discord.SelectOption(label=p, value=p) for p in planes]
        super().__init__(placeholder="Seleziona l'aereo con cui vuoi volare", min_values=1, max_values=1, options=options)
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.image_url = image_url

    async def callback(self, interaction: discord.Interaction):
        chosen_plane = self.values[0]
        # Aggiorna il piano selezionato per tutti i ruoli attivi
        for role in self.active_roles:
            if self.active_roles[role]["plane"] != "Non Attivo":
                self.active_roles[role]["plane"] = chosen_plane
        # Ricrea la view di prenotazione usando l'immagine selezionata
        view = BookingView(self.data, self.desc, self.active_roles, chosen_plane, self.image_url)
        embed = generate_embed(self.data, self.desc, self.active_roles, self.image_url)
        await interaction.response.edit_message(embed=embed, view=view)
