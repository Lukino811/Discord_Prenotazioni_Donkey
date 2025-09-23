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

# ============================ RUOLI, AEREI E PRENOTAZIONI ============================
class BookingButton(discord.ui.Button):
    def __init__(self, role, data, desc, active_roles, plane):
        is_active = active_roles[role]["plane"] == plane
        color = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
        super().__init__(label=role, style=color, disabled=not is_active)
        self.role_name = role
        self.data = data
        self.desc = desc
        self.active_roles = active_roles
        self.plane = plane

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        already_in_role = None
        for r, info in self.active_roles.items():
            if user in info["users"]:
                already_in_role = r
                break

        if already_in_role and already_in_role != self.role_name:
            await interaction.response.send_message(f"⚠️ Sei già prenotato in **{already_in_role}**! Rimuoviti prima da quel ruolo.", ephemeral=True)
            return

        role_info = self.active_roles[self.role_name]

        if user in role_info["users"]:
            role_info["users"].remove(user)
            save_bookings()
            embed = generate_embed(self.data, self.desc, self.active_roles, self.active_roles.get('image', BACKGROUND_URL))
            await interaction.response.edit_message(embed=embed, view=self.view)
            await interaction.followup.send(f"❌ Hai rimosso la tua prenotazione da **{self.role_name}**.", ephemeral=True)
            return

        if len(role_info["users"]) >= role_info["slots"]:
            await interaction.response.send_message(f"⚠️ {self.role_name} è già pieno!", ephemeral=True)
            return

        role_info["users"].append(user)
        save_bookings()
        embed = generate_embed(self.data, self.desc, self.active_roles, self.active_roles.get('image', BACKGROUND_URL))
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send(f"✅ Prenotazione in **{self.role_name}** confermata!", ephemeral=True)

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL

    async def continue_setup(self, interaction: discord.Interaction):
        await interaction.followup.send("📝 Inserisci i ruoli per l'evento:", ephemeral=True)
        await interaction.followup.send_modal(RoleInput(self))  # Assicurati che RoleInput sia definito correttamente

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane_choice = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {"plane": plane_choice, "slots": DEFAULT_SLOTS, "users": []}
        bookings[self.data] = active_roles
        save_bookings()
        embed = generate_embed(self.data, self.desc, active_roles, self.selected_image)
        await interaction.followup.send(embed=embed)

# ============================ COMANDO SLASH ============================
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli, aerei e scelta immagine")
@app_commands.describe(
    data="Data della missione (es. 2025-09-22 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    view = ImageSelectView(setup)
    await interaction.response.send_message("📸 Scegli un'immagine per l'evento:", view=view, ephemeral=True)

# ============================ ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")
    try:
        for guild_id in GUILD_IDS:
            synced = await bot.tree.sync(guild=discord.Object(id=guild_id))
            print(f"🔄 Sincronizzati {len(synced)} comandi slash per guild {guild_id}")
    except Exception as e:
        print(f"Errore sync: {e}")

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