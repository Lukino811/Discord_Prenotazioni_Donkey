import discord
from discord import app_commands
from discord.ext import commands
import json, os
from flask import Flask
from threading import Thread

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_IDS = [1234567890]  # 🔧 ID delle tue guild
BOOKINGS_FILE = "bookings.json"
MAX_ROLES = 5
DEFAULT_SLOTS = 4

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

# ============================ GESTIONE PRENOTAZIONI ============================
bookings = {}

def load_bookings():
    global bookings
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, "r") as f:
            bookings = json.load(f)

def save_bookings():
    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=4)

load_bookings()

# ============================ GENERAZIONE EMBED ============================
def generate_embed(data, desc, roles):
    embed = discord.Embed(title=f"Prenotazioni - {data}", description=desc, color=0x00ff00)
    for role, info in roles.items():
        users = ", ".join(info["users"]) if info["users"] else "Nessuno"
        embed.add_field(
            name=f"{role} ({info['plane']})",
            value=f"Posti: {len(info['users'])}/{info['slots']}\nUtenti: {users}",
            inline=False
        )
    return embed

# ============================ SELECT AEREO ============================
class PlaneSelectForRole(discord.ui.Select):
    def __init__(self, parent_view, role_name):
        options = [
            discord.SelectOption(label="F-16C", value="F-16C"),
            discord.SelectOption(label="FA-18C", value="FA-18C"),
            discord.SelectOption(label="Non Attivo", value="Non Attivo")
        ]
        super().__init__(placeholder=f"Scegli aereo per {role_name}", options=options)
        self.parent_view = parent_view
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_planes[self.role_name] = self.values[0]
        await interaction.response.send_message(
            f"Aereo per ruolo **{self.role_name}** impostato su **{self.values[0]}**",
            ephemeral=True
        )
        if len(self.parent_view.roles) < MAX_ROLES:
            await interaction.followup.send(
                "Vuoi aggiungere un nuovo ruolo o confermare l'evento?",
                view=RoleSetupView(self.parent_view),
                ephemeral=True
            )
        else:
            await self.parent_view.finish_setup(interaction)

# ============================ PULSANTI ============================
class SetPlaneButton(discord.ui.Button):
    def __init__(self, parent_view, role_name):
        super().__init__(label="Imposta Aereo", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction):
        view = discord.ui.View()
        view.add_item(PlaneSelectForRole(self.parent_view, self.role_name))
        await interaction.response.send_message(
            f"Seleziona l'aereo per il ruolo **{self.role_name}**:",
            view=view,
            ephemeral=True
        )

class AddRoleButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Aggiungi Ruolo", style=discord.ButtonStyle.secondary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleInput(self.parent_view))

class ConfirmEventButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Conferma Evento", style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.finish_setup(interaction)

class RoleSetupView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=None)
        self.add_item(AddRoleButton(parent_view))
        self.add_item(ConfirmEventButton(parent_view))

# ============================ MODAL ============================
class RoleInput(discord.ui.Modal, title="Aggiungi Ruolo"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.role_name = discord.ui.TextInput(label="Nome del Ruolo", required=True)
        self.add_item(self.role_name)

    async def on_submit(self, interaction: discord.Interaction):
        role_name = str(self.role_name.value)
        if len(self.parent_view.roles) >= MAX_ROLES:
            await interaction.response.send_message(
                "Hai raggiunto il limite massimo di ruoli!",
                ephemeral=True
            )
            return
        self.parent_view.roles.append(role_name)
        view = discord.ui.View()
        view.add_item(SetPlaneButton(self.parent_view, role_name))
        await interaction.response.send_message(
            f"Ruolo **{role_name}** aggiunto! Ora imposta l'aereo:",
            view=view,
            ephemeral=True
        )

# ============================ EVENT SETUP ============================
class EventSetupView:
    def __init__(self, data, desc):
        self.data = data
        self.desc = desc
        self.roles = []
        self.selected_planes = {}

    async def start(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleInput(self))

    async def finish_setup(self, interaction: discord.Interaction):
        active_roles = {}
        for role in self.roles:
            plane_choice = self.selected_planes.get(role, "Non Attivo")
            active_roles[role] = {
                "plane": plane_choice,
                "slots": DEFAULT_SLOTS,
                "users": []
            }
        bookings[self.data] = active_roles
        save_bookings()
        embed = generate_embed(self.data, self.desc, active_roles)
        await interaction.followup.send(embed=embed)

# ============================ COMANDO SLASH ============================
@app_commands.command(name="prenotazioni", description="Crea un evento con ruoli e aerei")
@app_commands.describe(
    data="Data della missione (es. 2025-09-22 18:00)",
    desc="Breve descrizione della missione"
)
async def prenotazioni(interaction: discord.Interaction, data: str, desc: str):
    setup = EventSetupView(data, desc)
    await setup.start(interaction)

for guild_id in GUILD_IDS:
    bot.tree.add_command(prenotazioni, guild=discord.Object(id=guild_id))

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