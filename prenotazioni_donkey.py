# ============================ CONFIG ============================
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# Token del bot (variabile d'ambiente)
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

# Guild di test
GUILD_ID = 1358713154116259892

# Config default
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
MAX_ROLES = 5
DEFAULT_SLOTS = 4
PLANES = ["FA-18C", "F-16C"]

# ============================ BOT ============================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================ PERSISTENZA ============================
if os.path.exists("prenotazioni.json"):
    with open("prenotazioni.json", "r") as f:
        bookings = json.load(f)
else:
    bookings = {}

def save_bookings():
    with open("prenotazioni.json", "w") as f:
        json.dump(bookings, f, indent=4)

# ============================ HELPERS ============================
def generate_embed(data: str, desc: str, active_roles: dict, image_url: str = BACKGROUND_URL):
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

# ============================ VIEWS E BUTTON ============================
class ImageSelectButton(discord.ui.Button):
    def __init__(self, parent_view, label, is_default=False):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.is_default = is_default

    async def callback(self, interaction: discord.Interaction):
        if self.is_default:
            self.parent_view.selected_image = BACKGROUND_URL
            await interaction.response.send_message("🖼️ Usata immagine di default!", ephemeral=True)
            await self.parent_view.continue_setup(interaction)
        else:
            await interaction.response.send_modal(ImageLinkModal(self.parent_view))

class ImageSelectView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.add_item(ImageSelectButton(parent_view, "Usa immagine di default", is_default=True))
        self.add_item(ImageSelectButton(parent_view, "Inserisci link immagine personalizzata", is_default=False))

class ImageLinkModal(discord.ui.Modal, title="Inserisci link immagine personalizzata"):
    image_url = discord.ui.TextInput(label="URL immagine", placeholder="https://...", max_length=500)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.selected_image = self.image_url.value.strip() or BACKGROUND_URL
        await interaction.response.send_message("📸 Immagine personalizzata impostata!", ephemeral=True)
        await self.parent_view.continue_setup(interaction)

class PlaneButton(discord.ui.Button):
    def __init__(self, plane, parent_view, role):
        super().__init__(label=plane, style=discord.ButtonStyle.primary)
        self.plane = plane
        self.parent_view = parent_view
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_planes[self.role] = self.plane
        await interaction.response.send_message(f"Aereo **{self.plane}** assegnato al ruolo **{self.role}**.", ephemeral=True)
        await self.parent_view.ask_next_role(interaction)

class ConfirmEventButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Conferma evento", style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.finish_setup(interaction)

class PlaneSelectView(discord.ui.View):
    def __init__(self, parent_view, role):
        super().__init__(timeout=None)
        self.parent_view = parent_view
        self.role = role
        for plane in PLANES:
            self.add_item(PlaneButton(plane, parent_view, role))
        self.add_item(ConfirmEventButton(parent_view))

class BookingButton(discord.ui.Button):
    def __init__(self, role, plane, active_roles):
        super().__init__(label=f"{role} - {plane}", style=discord.ButtonStyle.primary)
        self.role = role
        self.plane = plane
        self.active_roles = active_roles

    async def callback(self, interaction: discord.Interaction):
        # Rimuovi l'utente da eventuali altri ruoli
        for r, info in self.active_roles.items():
            if interaction.user.name in info["users"]:
                info["users"].remove(interaction.user.name)
        # Aggiungi all'attuale
        self.active_roles[self.role]["users"].append(interaction.user.name)
        embed = generate_embed(list(bookings.keys())[-1], "", self.active_roles)
        await interaction.response.edit_message(embed=embed, view=BookingView(self.active_roles))

class BookingView(discord.ui.View):
    def __init__(self, active_roles):
        super().__init__(timeout=None)
        for role in active_roles:
            for plane in PLANES:
                self.add_item(BookingButton(role, plane, active_roles))

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL
        self.role_index = 0

    async def continue_setup(self, interaction: discord.Interaction):
        # Se abbiamo raggiunto il massimo o vogliamo confermare evento
        if self.role_index >= MAX_ROLES:
            await self.finish_setup(interaction)
            return

        from discord.ui import Modal, TextInput

        class RoleInput(Modal, title="Aggiungi Ruolo"):
            role_name = TextInput(label="Nome ruolo", placeholder="Scrivi il nome del ruolo", max_length=50)

            def __init__(self, parent):
                super().__init__()
                self.parent_view = parent

            async def on_submit(self, interaction: discord.Interaction):
                role = self.role_name.value.strip()
                self.parent_view.roles.append(role)
                await interaction.response.send_message(f"Ruolo **{role}** aggiunto! Scegli l'aereo:", ephemeral=True, view=PlaneSelectView(self.parent_view, role))

        await interaction.response.send_modal(RoleInput(self))

    async def ask_next_role(self, interaction: discord.Interaction):
        self.role_index += 1
        if self.role_index < MAX_ROLES:
            await self.continue_setup(interaction)
        else:
            await self.finish_setup(interaction)

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane_choice = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {"plane": plane_choice, "slots": DEFAULT_SLOTS, "users": []}
        bookings[self.data] = active_roles
        save_bookings()
        embed = generate_embed(self.data, self.desc, active_roles, self.selected_image)
        await interaction.followup.send(embed=embed, view=BookingView(active_roles))

# ============================ COMANDO SLASH ============================
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(data="Data della missione", desc="Breve descrizione della missione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    await interaction.response.send_message("📸 Scegli un'immagine per l'evento:", ephemeral=True, view=ImageSelectView(setup))

# ============================ ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {GUILD_ID}: {[c.name for c in synced]}")
    except Exception as e:
        print(f"Errore sync per guild {GUILD_ID}: {e}")

# ============================ WEB SERVER ============================
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run).start()

# ============================ AVVIO BOT ============================
bot.run(TOKEN)
