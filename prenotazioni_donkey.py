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
GUILD_IDS = [1358713154116259892, 687741871757197312]

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
    embed = discord.Embed(
        title="📋 Prenotazioni Piloti",
        description=f"📅 Missione: {data}\n📝 {desc}",
        color=0x1abc9c
    )
    for role, info in active_roles.items():
        stato = "✅ Attivo" if info["plane"] != "Non Attivo" else "❌ Non Attivo"
        piloti = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(
            name=f"{role} ({len(info['users'])}/{info['slots']}) - {stato} - {info['plane']}",
            value=f"Prenotati: {piloti}",
            inline=False
        )
    embed.set_footer(text="Prenota cliccando i pulsanti qui sotto ✈️")
    embed.set_image(url=image_url)
    return embed

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}
        self.selected_image = BACKGROUND_URL

    async def continue_setup(self, interaction: discord.Interaction):
        from discord.ui import Modal, TextInput

        class RoleInput(Modal, title="Aggiungi Ruolo"):
            role_name = TextInput(label="Nome ruolo", placeholder="Scrivi il nome del ruolo", max_length=50)

            def __init__(self, parent):
                super().__init__()
                self.parent = parent

            async def on_submit(self, interaction: discord.Interaction):
                role = self.role_name.value.strip()
                self.parent.roles.append(role)
                try:
                    await interaction.response.send_message(
                        f"Ruolo **{role}** aggiunto! Seleziona l'aereo:",
                        ephemeral=True,
                        view=PlaneSelectForRoleView(self.parent, role)
                    )
                except Exception:
                    await interaction.followup.send(f"⚠️ Errore durante la selezione aereo per **{role}**", ephemeral=True)

        try:
            if interaction.response.is_done():
                await interaction.followup.send_modal(RoleInput(self))
            else:
                await interaction.response.send_modal(RoleInput(self))
        except Exception as e:
            await interaction.followup.send(f"⚠️ Errore durante apertura modal: {e}", ephemeral=True)

    async def ask_next_role_or_confirm(self, interaction: discord.Interaction):
        if len(self.roles) < MAX_ROLES:
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

# ============================ VIEWS ============================
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
        self.add_item(ImageSelectButton(parent_view, "Usa immagine di default", is_default=True))
        self.add_item(ImageSelectButton(parent_view, "Inserisci link immagine personalizzata", is_default=False))

class PlaneSelectForRole(discord.ui.Select):
    def __init__(self, parent_view, role_name):
        options = [discord.SelectOption(label=p, value=p) for p in PLANES + ["Non Attivo"]]
        super().__init__(placeholder=f"Scegli aereo per {role_name}", min_values=1, max_values=1, options=options)
        self.parent_view = parent_view
        self.role_name = role_name
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_planes[self.role_name] = self.values[0]
        await self.parent_view.ask_next_role_or_confirm(interaction)

class PlaneSelectForRoleView(discord.ui.View):
    def __init__(self, parent_view, role_name):
        super().__init__(timeout=None)
        self.add_item(PlaneSelectForRole(parent_view, role_name))

class BookingButton(discord.ui.Button):
    def __init__(self, role, active_roles):
        super().__init__(label=role, style=discord.ButtonStyle.primary)
        self.role = role
        self.active_roles = active_roles
    async def callback(self, interaction: discord.Interaction):
        user = interaction.user.name
        role_info = self.active_roles[self.role]
        if user in role_info["users"]:
            role_info["users"].remove(user)
        elif len(role_info["users"]) < role_info["slots"]:
            role_info["users"].append(user)
        await interaction.response.edit_message(embed=generate_embed(list(bookings.keys())[-1], "", self.active_roles), view=BookingView(self.active_roles))

class BookingView(discord.ui.View):
    def __init__(self, active_roles):
        super().__init__(timeout=None)
        for role in active_roles:
            self.add_item(BookingButton(role, active_roles))

# ============================ COMANDO SLASH ============================
@bot.tree.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(data="Data della missione", desc="Breve descrizione della missione")
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    # Defer per evitare Unknown interaction
    await interaction.response.defer(ephemeral=True)
    # Invia la view per la scelta immagine come followup
    await interaction.followup.send(
        "📸 Scegli un'immagine per l'evento:",
        view=ImageSelectView(setup),
        ephemeral=True
    )

# ============================ ON_READY ============================
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}\n")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Sincronizzati {len(synced)} comandi globali")
    except Exception as e:
        print(f"❌ Errore sync comandi: {e}")

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