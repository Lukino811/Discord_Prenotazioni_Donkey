# ============================ CONFIG ============================
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# Ottieni il token del bot dall'ambiente
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN non trovato — imposta la variabile d'ambiente")

# Lista server
GUILD_IDS = [1358713154116259892, 687741871757197312]

# Impostazioni default
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/710523786558046298/1403090934857728001/BCO.png"
MAX_ROLES = 5
DEFAULT_SLOTS = 4

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

# ============================ FUNZIONE EMBED ============================
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
        self.add_item(ImageSelectButton(parent_view, label="Usa immagine di default", is_default=True))
        self.add_item(ImageSelectButton(parent_view, label="Inserisci link immagine personalizzata", is_default=False))

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL

    async def continue_setup(self, interaction: discord.Interaction):
        # Modal per aggiunta ruolo
        from discord.ui import Modal, TextInput

        class RoleInput(Modal, title="Aggiungi Ruolo"):
            role_name = TextInput(label="Nome ruolo", placeholder="Scrivi il nome del ruolo", max_length=50)

            def __init__(self, parent):
                super().__init__()
                self.parent = parent

            async def on_submit(self, interaction):
                self.parent.roles.append(self.role_name.value.strip())
                await interaction.response.send_message(f"Ruolo **{self.role_name.value.strip()}** aggiunto.", ephemeral=True)
                await self.parent.finish_setup(interaction)

        await interaction.response.send_modal(RoleInput(self))

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane_choice = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {"plane": plane_choice, "slots": DEFAULT_SLOTS, "users": []}
        bookings[self.data] = active_roles
        save_bookings()
        embed = generate_embed(self.data, self.desc, active_roles, self.selected_image)
        await interaction.followup.send(embed=embed)

# ============================ REGISTRAZIONE COMANDO SLASH ============================
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli, aerei e scelta immagine")
@app_commands.describe(
    data="Data della missione (es. 2025-09-22 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    view = ImageSelectView(setup)
    await interaction.response.send_message("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)

for gid in GUILD_IDS:
    try:
        bot.tree.add_command(prenotazioni, guild=discord.Object(id=gid))
        print(f"🔧 Command /prenotazioni aggiunto localmente per guild {gid}")
    except Exception as e:
        print(f"Errore add_command per guild {gid}: {e}")

# ============================ ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    for gid in GUILD_IDS:
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=gid))
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {gid}: {[c.name for c in synced]}")
        except Exception as e:
            print(f"Errore sync per guild {gid}: {e}")

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